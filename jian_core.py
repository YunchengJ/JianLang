#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《简》(Jian-Lang v0.9-Draft) 轻量化双模单字系统开发语言·参考内核与解析原型
本原型包含以下核心功能：
1. 以 opcode_table_128.json 为唯一事实源（Single Source of Truth），支持 cn/sym/ascii 全映射，未知算子 Fail-Closed 报错（修复 !!brk -> 0x57）
2. 严格 1:1 正交双射：加法唯一为【增(+)】，减法唯一为【减(-)】，【并(||)】专司并行，【损(@degrade)】专司 API 折损，【<=】唯一为小等，【自】符号为 <-:
3. 【法—项—纲】全周期 Read-Set（覆盖【法】与【项】全部读取）+ Write-Buffer 暂存原子提交 + op_ti (替) 递增 epoch + 【立项/立行】悲观独占锁
4. 自愈调度器内置连续【立断】活锁（Livelock）检测：正反两序连续熔断无进展时自动触发【立结】停机
5. 式[...] 双模沙盒：支持括号符号态与无括号波次态，落实同波次操作数不重叠并行公理与相邻同级最左结合律（1 先减 2 先减 3 == -4）
6. 【包：封/拆】内置 SHA-256 防篡改签名校验；数据面支持寄存器级【视:不可】隐私保护（阻断【寻/立寻】越权扫描）
7. 内置《简》源码文本解析执行器（execute_jian_source），可直接解析运行《简》源码字符串
"""

from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Set, Tuple


# ============================================================================
# 1. 从 opcode_table_128.json 加载单一事实源（Fail-Closed 7-Bit 编码器）
# ============================================================================

_SPEC_DIR = Path(__file__).resolve().parent
_OPCODE_JSON_PATH = _SPEC_DIR / "opcode_table_128.json"
_SPEC_DATA = json.loads(_OPCODE_JSON_PATH.read_text(encoding="utf-8"))

OPCODE_LOOKUP: Dict[str, int] = {}
IMPLEMENTED_OPCODES: List[str] = []
SPEC_ONLY_OPCODES: List[str] = []

for entry in _SPEC_DATA["base_opcodes_64"]:
    code_int = int(entry["code"], 16)
    cn_tok = entry["cn"]
    sym_tok = entry["sym"]
    ascii_tok = entry["ascii"]
    OPCODE_LOOKUP[cn_tok] = code_int
    OPCODE_LOOKUP[sym_tok] = code_int
    OPCODE_LOOKUP[ascii_tok] = code_int
    if entry.get("implemented_in_core", False):
        IMPLEMENTED_OPCODES.append(cn_tok)
    else:
        SPEC_ONLY_OPCODES.append(cn_tok)

SYMBOL_ALIASES: Dict[str, str] = {}
for group in ("arrows_and_pipes", "math_and_logic"):
    SYMBOL_ALIASES.update(_SPEC_DATA["dual_mode_aliases"].get(group, {}))

CN_NUMERALS: Dict[str, int] = _SPEC_DATA["dual_mode_aliases"]["numerals"]

# 同槽位成员字（大/小/等 族、索/参/合/引 族、实/尽 族、状态常量族）-> 所属基础算子 cn
FAMILY_MEMBERS: Dict[str, str] = {
    k: v
    for k, v in _SPEC_DATA["dual_mode_aliases"].get("opcode_family_members", {}).items()
    if not k.startswith("_")
}

# 式[...] 内可直接使用的常量字面量（规范域 8：真(1)/假(0)、空(null)）
FORMULA_CONSTANTS: Dict[str, Any] = {"真": True, "假": False, "空": None}


def encode_opcode(token: str) -> int:
    """
    将单字、符号或【立 / !!】抢占算子编译为 7-bit (0x00..0x7F) 微指令码。
    严格 Fail-Closed：任何未知算子直接抛出 ValueError，绝不静默回退至 0x3D(真)！
    """
    tok = token.strip()
    preempt = False
    if tok.startswith("立") and len(tok) > 1:
        preempt = True
        tok = tok[1:]
    elif tok.startswith("!!") and len(tok) > 2:
        preempt = True
        tok = tok[2:]

    # 先按 ASCII 助记符直查（如 `>`、`gt`），再走符号别名，最后归一同槽位成员字
    if tok not in OPCODE_LOOKUP:
        tok = SYMBOL_ALIASES.get(tok, tok)
        tok = FAMILY_MEMBERS.get(tok, tok)
    if tok not in OPCODE_LOOKUP:
        raise ValueError(f"Fail-Closed 词法错误：未知算子或非法助记符 '{token}' (归一化后: '{tok}')")

    base_code = OPCODE_LOOKUP[tok]
    return (base_code | 0x40) if preempt else base_code


# ============================================================================
# 2. 式[...] 双模波次并行算式求值器（严格正交双射 + 相邻同级最左结合）
# ============================================================================

class WavefrontFormulaEngine:
    """
    支持双模等价求值：
    - LLM 推荐（免括号嵌套层级汉语运算法）：
      式[x甲 先先减 乙 后幂 2 后后增 x乙 先先减 乙 后幂 2 后后后商 2 后乘 戊 先先幂 2]
    - 人工推荐（原始标准阿拉伯线性表达式）：
      式[((x甲 - 乙) ^ 2 + (x乙 - 乙) ^ 2) / (2 * (戊 ^ 2))]
    公理：
    1. 严格一字一义：加法唯一为 增(+)，减法唯一为 减(-)，绝不混用 并/损。
    2. 同波次算子仅当左右操作数区间互不重叠时可并行归约；相邻共享操作数严格按从左到右结合。
    3. 优先级 rank（越小越先算）：先ⁿ 前缀 = -10n ＜ 符号默认 rank（^ -5 ＜ 一元± -3 ＜ * / % -2 ＜ + - 0 ＜ 比较 5）＜ 后ⁿ 前缀 = +10n。
       即波次前缀恒先于符号默认优先级：式[x甲 ^ 乙 - 2] = (x甲^乙)-2，式[x甲 ^ 乙 先减 2] = x甲^(乙-2)。
    4. 无前缀的 ^ / ** / 幂 按常规数学右结合（2 ^ 3 ^ 2 = 512）；其余算子同 rank 最左结合。
    """
    BASE_OPS: Dict[str, Callable[[Any, Any], Any]] = {
        "增": lambda a, b: a + b,
        "+":  lambda a, b: a + b,
        "减": lambda a, b: a - b,
        "-":  lambda a, b: a - b,
        "乘": lambda a, b: a * b,
        "*":  lambda a, b: a * b,
        "商": lambda a, b: a / b,
        "除": lambda a, b: a / b,
        "/":  lambda a, b: a / b,
        "余": lambda a, b: a % b,
        "%":  lambda a, b: a % b,
        "幂": lambda a, b: a ** b,
        "^":  lambda a, b: a ** b,
        "**": lambda a, b: a ** b,
        "大": lambda a, b: a > b,
        ">":  lambda a, b: a > b,
        "小": lambda a, b: a < b,
        "<":  lambda a, b: a < b,
        "等": lambda a, b: a == b,
        "==": lambda a, b: a == b,
        "大等": lambda a, b: a >= b,
        ">=":   lambda a, b: a >= b,
        "小等": lambda a, b: a <= b,
        "<=":   lambda a, b: a <= b,
        "非等": lambda a, b: a != b,
        "!=":   lambda a, b: a != b,
    }

    @classmethod
    def parse_wave_operator(cls, tok: str) -> Optional[Tuple[int, Callable[[Any, Any], Any]]]:
        if tok in cls.BASE_OPS:
            default_rank = {
                "^": -5, "**": -5, "幂": -5,
                "*": -2, "乘": -2, "/": -2, "商": -2, "除": -2, "%": -2, "余": -2,
                "+": 0, "增": 0, "-": 0, "减": 0,
            }.get(tok, 5)
            return (default_rank, cls.BASE_OPS[tok])

        m = re.match(r"^(先+|后+)(增|减|乘|商|除|余|幂|大|小|等|大等|小等|非等)$", tok)
        if m:
            prefix, op_char = m.group(1), m.group(2)
            rank = -10 * len(prefix) if prefix.startswith("先") else +10 * len(prefix)
            return (rank, cls.BASE_OPS[op_char])
        return None

    # 一元正负号（仅符号态 `+` / `-`，出现在操作数位置时生效）；
    # 结合力介于 幂(-5) 与 乘除(-2) 之间：-2 ^ 2 == -4，2 * -3 == -6，2 ^ -1 == 0.5
    UNARY_RANK = -3
    UNARY_OPS: Dict[str, Callable[[Any], Any]] = {
        "-": lambda a: -a,
        "+": lambda a: +a,
    }
    # 仅无波次前缀的乘方按常规数学右结合；带 先/后 前缀的波次算子一律最左结合（规范 1.1-3）
    RIGHT_ASSOC_OPS: Set[str] = {"^", "**", "幂"}

    _TOKEN_RE = re.compile(
        r"(?P<ws>\s+)"
        r"|(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+\-]?\d+)?)"
        r"|(?P<op>\*\*|==|>=|<=|!=|[+\-*/^%><()])"
        r"|(?P<word>[^\s+\-*/^%><()=!]+)"
    )

    @classmethod
    def _normalize_sandbox(cls, expr_str: str) -> str:
        """剥掉外层 式[...] / $[...]，并把内嵌的 式[...] / $[...] 改写为圆括号分组（支持规范示例 2 模式 B 混调）。"""
        out: List[str] = []
        stack: List[bool] = []  # True = 式[ / $[ 分组，False = 普通数据槽 [ ]
        i = 0
        while i < len(expr_str):
            two = expr_str[i : i + 2]
            if two in ("式[", "$["):
                stack.append(True)
                out.append("(")
                i += 2
                continue
            ch = expr_str[i]
            if ch == "[":
                stack.append(False)
                out.append(ch)
            elif ch == "]":
                if not stack:
                    raise ValueError(f"式 语法错误：多余的 ']'：{expr_str!r}")
                out.append(")" if stack.pop() else ch)
            else:
                out.append(ch)
            i += 1
        if stack:
            raise ValueError(f"式 语法错误：方括号未闭合：{expr_str!r}")
        return "".join(out)

    @classmethod
    def _tokenize(cls, expr_str: str) -> List[Tuple[str, str]]:
        tokens: List[Tuple[str, str]] = []
        pos = 0
        while pos < len(expr_str):
            m = cls._TOKEN_RE.match(expr_str, pos)
            if m is None or m.end() == pos:
                raise ValueError(f"式 词法错误：位置 {pos} 处无法识别的字符 {expr_str[pos]!r}：{expr_str!r}")
            kind = m.lastgroup
            if kind != "ws":
                tokens.append((kind, m.group(kind)))
            pos = m.end()
        return tokens

    @classmethod
    def eval_expr(cls, expr_str: str, env: Mapping[str, Any]) -> Any:
        """
        Fail-Closed 求值：括号失配、操作数/算子缺失、相邻操作数、未定义标识符一律抛出 ValueError，
        不再以字符串回代中间结果（修复负数中间值、1e-05 等科学计数法回代导致的死循环与误算）。
        """
        tokens = cls._tokenize(cls._normalize_sandbox(expr_str.strip()))

        # 圆括号按栈分组，组内结果以原生 Python 值保留，不做字符串往返
        stack: List[List[Any]] = [[]]
        for kind, text in tokens:
            if text == "(":
                stack.append([])
            elif text == ")":
                if len(stack) == 1:
                    raise ValueError(f"式 语法错误：多余的 ')'：{expr_str!r}")
                group = stack.pop()
                stack[-1].append(("VAL", cls._reduce(group, expr_str)))
            elif kind == "num":
                stack[-1].append(("VAL", float(text) if any(c in text for c in ".eE") else int(text)))
            elif kind == "op":
                stack[-1].append(("RAW_OP", text))
            else:
                if cls.parse_wave_operator(text) is not None:
                    stack[-1].append(("RAW_OP", text))
                else:
                    stack[-1].append(("VAL", cls._resolve_atom(text, env, strict=True)))
        if len(stack) != 1:
            raise ValueError(f"式 语法错误：圆括号未闭合：{expr_str!r}")
        return cls._reduce(stack[0], expr_str)

    @classmethod
    def _resolve_atom(cls, tok: str, env: Mapping[str, Any], strict: bool = False) -> Any:
        tok = tok.strip("[]")
        if tok in env:
            return env[tok]
        if tok in CN_NUMERALS:
            return CN_NUMERALS[tok]
        if tok in FORMULA_CONSTANTS:
            return FORMULA_CONSTANTS[tok]
        try:
            return int(tok)
        except ValueError:
            pass
        try:
            return float(tok)
        except ValueError:
            pass
        if strict:
            raise ValueError(f"式 Fail-Closed：未定义的标识符 '{tok}'")
        return tok

    @classmethod
    def _reduce(cls, raw: List[Any], src: str) -> Any:
        """把一组 [VAL / RAW_OP] 按波次 rank 归约；同 rank 相邻共享操作数严格最左结合。"""
        if not raw:
            raise ValueError(f"式 语法错误：空表达式或空括号：{src!r}")

        # 1) 依据位置区分一元/二元算子，并校验「操作数-算子-操作数」交替结构
        items: List[Tuple[Any, ...]] = []
        expect_operand = True
        for item in raw:
            if item[0] == "VAL":
                if not expect_operand:
                    raise ValueError(f"式 语法错误：相邻操作数之间缺少算子：{src!r}")
                items.append(item)
                expect_operand = False
                continue
            text = item[1]
            if expect_operand:
                if text in cls.UNARY_OPS:
                    items.append(("UOP", cls.UNARY_RANK, cls.UNARY_OPS[text], text))
                    continue
                raise ValueError(f"式 语法错误：算子 '{text}' 缺少左操作数：{src!r}")
            op_info = cls.parse_wave_operator(text)
            if op_info is None:
                raise ValueError(f"式 语法错误：非法算子 '{text}'：{src!r}")
            items.append(("OP", op_info[0], op_info[1], text))
            expect_operand = True
        if expect_operand:
            raise ValueError(f"式 语法错误：表达式以算子结尾，缺少右操作数：{src!r}")

        # 2) 按 rank 做优先级爬升（Pratt）：rank 越小结合越紧；
        #    同 rank 默认最左结合，仅无前缀的 ^ / ** / 幂 右结合（2 ^ 3 ^ 2 == 512）。
        #    对纯二元链，这与「每轮归约最小 rank、同 rank 取最左」完全等价；一元号的右操作数吸收所有更紧的算子。
        pos = 0

        def parse(max_rank: float) -> Any:
            nonlocal pos
            head = items[pos]
            pos += 1
            if head[0] == "UOP":
                lhs = head[2](parse(head[1]))
            else:
                lhs = head[1]
            while pos < len(items):
                op = items[pos]
                if op[1] > max_rank:
                    break
                pos += 1
                right_assoc = op[3] in cls.RIGHT_ASSOC_OPS
                rhs = parse(op[1] if right_assoc else op[1] - 0.5)
                lhs = op[2](lhs, rhs)
            return lhs

        result = parse(float("inf"))
        assert pos == len(items), "优先级爬升状态机异常：存在未消费的记号"
        return result


# ============================================================================
# 3. 《简》核心虚拟机（全周期 Read-Set + Write-Buffer + 活锁熔断 + 寄存器级隐私）
# ============================================================================

class _VMEnv(Mapping[str, Any]):
    """
    式[...] 求值用的寄存器视图：每次取值都经由 op_qu，
    因而同样受【废】脏读拦截、事务读集登记与 Read-Your-Own-Writes 约束（不再直接读 registers 字典绕过检查）。
    """

    def __init__(self, vm: "JianRuntimeVM", extra: Optional[Dict[str, Any]] = None) -> None:
        self._vm = vm
        self._extra = extra or {}

    def _names(self) -> Set[str]:
        names = set(self._vm.registers) | set(self._extra)
        buf = self._vm._active_write_buffer
        if buf:
            names |= {k for k, e in buf.items() if e[0] != "放"}
            names -= {k for k, e in buf.items() if e[0] == "放"}
        return names

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._names()

    def __getitem__(self, key: str) -> Any:
        if key in self._extra:
            return self._extra[key]
        if key not in self:
            raise KeyError(key)
        return self._vm.op_qu(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._names())

    def __len__(self) -> int:
        return len(self._names())


class JianRuntimeVM:
    def __init__(self) -> None:
        self.registers: Dict[str, Any] = {}
        self.epochs: Dict[str, int] = {}             # 寄存器版本世代号
        self.types: Dict[str, str] = {}
        self.visibility: Dict[str, str] = {}         # 数据面零信任：'可' (默认公开) | '不可' (私有隐身)
        self.lifecycle: Dict[str, str] = {}          # '存' | '归' | '废' | '放'
        self.exclusive_locks: Set[str] = set()       # 悲观独占锁集合（由【立项/立行】持有）
        self._held_locks: Set[str] = set()           # 当前执行上下文（正在运行的【立项】）自己持有的锁
        self.state_chain: Dict[str, str] = {}        # Prefix Key-Chain 状态表
        self.laws: Dict[str, Callable[["JianRuntimeVM", Any], bool]] = {}
        self.tasks: Dict[str, Callable[["JianRuntimeVM", Any, bool], bool]] = {}
        self.projs: Dict[str, str] = {}
        self.apis: Dict[str, Dict[str, Any]] = {}
        self.carry_break_flag: bool = False          # 【断 / 立断】中断标志
        self.halted: bool = False                    # 【结 / 立结】全局停机标志
        self._active_read_set: Optional[Dict[str, int]] = None
        # 写缓冲条目：寄存器名 -> (操作种类 存/归/替/废/放, 值, 类型, 可见性)
        self._active_write_buffer: Optional[Dict[str, Tuple[str, Any, str, str]]] = None
        self.console_out: List[Any] = []

    def _check_not_locked_by_other(self, name: str, current_holds_lock: bool = False) -> None:
        if name in self.exclusive_locks and not current_holds_lock and name not in self._held_locks:
            self.carry_break_flag = True
            raise RuntimeError(f"寄存器 [{name}] 正处于【立项】悲观独占锁保护中，并发访问被拒绝！")

    def _run_as_external_actor(self, hook: Callable[["JianRuntimeVM"], None]) -> None:
        """以「事务外的并发参与者」身份执行钩子：不继承本事务的读集、写缓冲与独占锁持有权。"""
        saved = (self._active_read_set, self._active_write_buffer, self._held_locks)
        self._active_read_set, self._active_write_buffer, self._held_locks = None, None, set()
        try:
            hook(self)
        finally:
            self._active_read_set, self._active_write_buffer, self._held_locks = saved

    def formula_env(self, extra: Optional[Dict[str, Any]] = None) -> _VMEnv:
        return _VMEnv(self, extra)

    def _buffer_write(self, name: str, kind: str, value: Any, reg_type: str, vis: str) -> bool:
        """若处于【项】事务期内，把修改记入写缓冲并返回 True；否则返回 False 由调用方直接提交。"""
        if self._active_write_buffer is None:
            return False
        self._active_write_buffer[name] = (kind, value, reg_type, vis)
        return True

    # ---- 四态内存生命周期 (MESI: 存 · 归 · 废 · 放) ----
    def op_cun(
        self,
        name: str,
        value: Any,
        reg_type: str = "数",
        vis: Optional[str] = None,
        holds_lock: bool = False,
    ) -> None:
        """【存】：若在【项】事务期内则写入暂存区 _active_write_buffer；否则直接提交并递增 epoch"""
        self._check_not_locked_by_other(name, holds_lock)
        eff_vis = vis if vis is not None else self.visibility.get(name, "可")
        if self._buffer_write(name, "存", value, reg_type, eff_vis):
            return
        self.registers[name] = value
        self.epochs[name] = self.epochs.get(name, 0) + 1
        self.types[name] = reg_type
        self.visibility[name] = eff_vis
        self.lifecycle[name] = "存"

    def op_gui(self, name: str, holds_lock: bool = False) -> None:
        """【归】：不释放槽位，状态与值归零复位，递增 epoch（事务内同样先进写缓冲，提交时再级联复位状态链）"""
        self._check_not_locked_by_other(name, holds_lock)
        buf = self._active_write_buffer
        t = buf[name][2] if buf is not None and name in buf else self.types.get(name, "数")
        zero_val = [] if t == "目" else ({} if t == "典" else 0)
        if self._buffer_write(name, "归", zero_val, t, self.visibility.get(name, "可")):
            return
        self.registers[name] = zero_val
        self.epochs[name] = self.epochs.get(name, 0) + 1
        self.types[name] = t
        self.lifecycle[name] = "归"
        for k in list(self.state_chain.keys()):
            if k.startswith(name):
                self.state_chain[k] = "未"

    def op_fei(self, name: str, holds_lock: bool = False) -> None:
        """【废】：标记脏数据墓碑，禁止下游读取，递增 epoch（事务内先进写缓冲，回滚时不留痕）"""
        self._check_not_locked_by_other(name, holds_lock)
        if self._buffer_write(name, "废", None, self.types.get(name, "数"), self.visibility.get(name, "可")):
            return
        self.lifecycle[name] = "废"
        self.epochs[name] = self.epochs.get(name, 0) + 1
        for k in list(self.state_chain.keys()):
            if k.startswith(name):
                self.state_chain[k] = "败"

    def op_fang(self, name: str, holds_lock: bool = False) -> None:
        """【放】：物理释放寄存器并级联销毁前缀 Key-Chain，递增 epoch（事务内先进写缓冲）"""
        self._check_not_locked_by_other(name, holds_lock)
        if self._buffer_write(name, "放", None, self.types.get(name, "数"), self.visibility.get(name, "可")):
            return
        self.registers.pop(name, None)
        self.epochs[name] = self.epochs.get(name, 0) + 1
        self.lifecycle[name] = "放"
        for k in list(self.state_chain.keys()):
            if k.startswith(name):
                del self.state_chain[k]

    def _apply_buffered(self, name: str, entry: Tuple[str, Any, str, str]) -> None:
        kind, value, reg_type, vis = entry
        if kind == "存":
            self.op_cun(name, value, reg_type, vis=vis)
        elif kind == "归":
            self.op_gui(name)
        elif kind == "替":
            self.op_ti(name, value)
        elif kind == "废":
            self.op_fei(name)
        elif kind == "放":
            self.op_fang(name)
        else:  # pragma: no cover - 防御性分支
            raise RuntimeError(f"未知写缓冲操作种类：{kind}")

    def op_qu(self, name: str) -> Any:
        """
        【取】：读取寄存器。
        - 若处于【法+项】事务周期内（_active_read_set 开启）：
          1. 若本事务 _active_write_buffer 已改写该寄存器，直接读出暂存新值（Read-Your-Own-Writes）；
          2. 否则自动将该寄存器及当前 epoch 纳入全周期读集（覆盖【法】和【项】自身的全部读取！）；
          3. 若此前在同一事务内已读过该寄存器，当场比对 epoch 是否被外部篡改。
        """
        if self._active_write_buffer is not None and name in self._active_write_buffer:
            kind, value = self._active_write_buffer[name][:2]
            if kind == "废":
                self.carry_break_flag = True
                raise RuntimeError(f"寄存器 [{name}] 已在本事务中被标记为【废】，禁止脏读！")
            return None if kind == "放" else value
        if self.lifecycle.get(name) == "废":
            self.carry_break_flag = True
            raise RuntimeError(f"寄存器 [{name}] 已被标记为【废】，禁止脏读！")
        if self._active_read_set is not None:
            cur_ep = self.epochs.get(name, 0)
            if name not in self._active_read_set:
                self._active_read_set[name] = cur_ep
            elif self._active_read_set[name] != cur_ep:
                self.carry_break_flag = True
                raise RuntimeError(f"TOCTOU 读集冲突：寄存器 [{name}] 在事务中途被并发修改！")
        return self.registers.get(name)

    # ---- 无指针全局内容寻址【寻 / 立寻】（遵守数据面【视:不可】隐私边界）与热替换【替 / 立替】 ----
    def op_xun(self, predicate_or_val: Any) -> Dict[str, Any]:
        """【寻】：仅遍历状态为有效且可见性为【可】的寄存器，严禁泄露【视:不可】私有寄存器！"""
        found: Dict[str, Any] = {}
        for k, v in self.registers.items():
            if self.lifecycle.get(k) == "废" or self.visibility.get(k, "可") == "不可":
                continue
            if callable(predicate_or_val):
                if predicate_or_val(v):
                    found[k] = v
            elif v == predicate_or_val:
                found[k] = v
        return found

    def op_ti(self, name: str, new_val: Any, holds_lock: bool = False) -> None:
        """【替 / 立替】：全局参数原子热替换（严格递增 epoch 以触发并发 CAS 校验！）
        规范 1.3-2：【项】内的 替 同样先进写缓冲，提交时才落盘。"""
        self._check_not_locked_by_other(name, holds_lock)
        if self._buffer_write(name, "替", new_val, self.types.get(name, "数"), self.visibility.get(name, "可")):
            return
        self.registers[name] = new_val
        self.epochs[name] = self.epochs.get(name, 0) + 1
        self.lifecycle[name] = "存"

    # ---- 严格首字优先 Prefix Key-Chain 状态机 (态[甲乙...]) ----
    def set_state_keychain(self, chain_key: str, val: str = "真") -> bool:
        for i in range(1, len(chain_key)):
            prefix = chain_key[:i]
            if self.state_chain.get(prefix) not in ("真", "成"):
                return False
        self.state_chain[chain_key] = val
        return True

    def check_state_keychain(self, chain_key: str, target: str = "真") -> bool:
        for i in range(1, len(chain_key) + 1):
            prefix = chain_key[:i]
            expected = target if i == len(chain_key) else "真"
            if self.state_chain.get(prefix) not in (expected, "成"):
                return False
        return True

    # ---- 【法 · 项 · 纲】三层注册（全周期 Read-Set + Write-Buffer + 立项独占锁） ----
    def register_fa_xiang_gang(
        self,
        prefix: str,
        fa_fn: Callable[["JianRuntimeVM", Any], bool],
        xiang_fn: Callable[["JianRuntimeVM", Any], None],
        lock_targets: Optional[List[str]] = None,
        between_check_and_use_hook: Optional[Callable[["JianRuntimeVM"], None]] = None,
        during_xiang_read_hook: Optional[Callable[["JianRuntimeVM"], None]] = None,
    ) -> None:
        law_name = f"{prefix}法"
        task_name = f"{prefix}项"
        proj_name = f"{prefix}纲"
        self.laws[law_name] = fa_fn

        def wrapped_task(vm: "JianRuntimeVM", arg: Any = None, preempt_exclusive: bool = False) -> bool:
            locked_keys = list(lock_targets or []) if preempt_exclusive else []
            # 规范 1.3-4：可重入（RLock）——本上下文已持有的锁不重复获取，也不在本层释放
            newly_locked = [k for k in locked_keys if k not in vm._held_locks]
            if newly_locked:
                # 【立项 / 立行】悲观独占访问模式：进入【法】前直接锁死目标寄存器
                if any(k in vm.exclusive_locks for k in newly_locked):
                    vm.carry_break_flag = True
                    return False
                vm.exclusive_locks.update(newly_locked)
            saved_held = vm._held_locks
            vm._held_locks = saved_held | set(locked_keys)

            # 开启横跨【法】与【项】全周期的 Read-Set 与 Write-Buffer
            # （若嵌套在外层【项】事务内，提交时并入外层读集/写缓冲，由外层统一 CAS 落盘）
            outer_r, outer_w = vm._active_read_set, vm._active_write_buffer
            vm._active_read_set = {}
            vm._active_write_buffer = {}
            try:
                ok = vm.laws[law_name](vm, arg)
                if not ok:
                    vm.carry_break_flag = True
                    return False

                if between_check_and_use_hook is not None:
                    vm._run_as_external_actor(between_check_and_use_hook)

                # 执行【项】：【项】内部调用的 op_qu 同样自动记入 _active_read_set，写入暂存至 _active_write_buffer
                xiang_fn(vm, arg)

                if during_xiang_read_hook is not None:
                    vm._run_as_external_actor(during_xiang_read_hook)

                # 终态原子提交闸门：校验【法】+【项】全周期读取过的所有寄存器 epoch 是否均未被外部篡改
                for reg_name, snap_epoch in vm._active_read_set.items():
                    if vm.epochs.get(reg_name, 0) != snap_epoch:
                        vm.carry_break_flag = True
                        return False

                read_items = dict(vm._active_read_set)
                write_items = list(vm._active_write_buffer.items())
                vm._active_read_set, vm._active_write_buffer = outer_r, outer_w
                if outer_r is not None:
                    for reg_name, snap_epoch in read_items.items():
                        if outer_r.setdefault(reg_name, snap_epoch) != snap_epoch:
                            vm.carry_break_flag = True
                            return False
                # 提交前先整体核验写集锁权限，避免写到一半才被他人独占锁拒绝而留下半提交状态
                for reg_name, _ in write_items:
                    vm._check_not_locked_by_other(reg_name)
                # 校验全部通过：将写缓冲原子刷入全局内存（或外层写缓冲）并递增 epoch
                for reg_name, entry in write_items:
                    vm._apply_buffered(reg_name, entry)

                vm.carry_break_flag = False
                return True
            except RuntimeError:
                vm.carry_break_flag = True
                return False
            finally:
                vm._active_read_set, vm._active_write_buffer = outer_r, outer_w
                vm._held_locks = saved_held
                for k in newly_locked:
                    vm.exclusive_locks.discard(k)

        self.tasks[task_name] = wrapped_task
        self.projs[proj_name] = task_name

    # ---- 自愈调度器（内置活锁 Livelock 连续熔断检测 -> 自动触发【立结】） ----
    def run_self_healing_scheduler(
        self,
        first_gang: str,
        second_gang: str,
        max_cycles: int = 6,
    ) -> List[Tuple[int, str, str, Dict[str, Any]]]:
        """
        行 甲纲 乙纲 循 先甲 后乙 若 断 则 先行 乙纲 后行 甲纲 复 循
        新增活锁熔断保护：若正反两序（先甲 -> 断 -> XCHG -> 先乙 -> 断）在同一状态世代下连续触发立断无任何推进，
        判定为两事务互斥活锁（Livelock），立即自动触发【立结】（halted=True）退出循环！
        """
        r8_slot, r9_slot = first_gang, second_gang
        trace: List[Tuple[int, str, str, Dict[str, Any]]] = []
        cycle = 0
        consecutive_breaks = 0

        while cycle < max_cycles and not self.halted:
            cycle += 1
            t1 = self.projs[r8_slot]
            self.tasks[t1](self, None, False)
            if self.carry_break_flag:
                consecutive_breaks += 1
                r8_slot, r9_slot = r9_slot, r8_slot
                self.carry_break_flag = False
                if consecutive_breaks >= 2:
                    self.halted = True
                    trace.append((cycle, "活锁熔断->立结", f"先:{r8_slot} 后:{r9_slot}", dict(self.registers)))
                    break
                trace.append((cycle, "立断->XCHG重排", f"先:{r8_slot} 后:{r9_slot}", dict(self.registers)))
                continue

            consecutive_breaks = 0
            t2 = self.projs[r9_slot]
            self.tasks[t2](self, None, False)
            if self.carry_break_flag:
                consecutive_breaks += 1
                r8_slot, r9_slot = r9_slot, r8_slot
                self.carry_break_flag = False
                trace.append((cycle, "立断->XCHG重排", f"先:{r8_slot} 后:{r9_slot}", dict(self.registers)))
                continue

            trace.append((cycle, "成->顺行", f"先:{r8_slot} 后:{r9_slot}", dict(self.registers)))
        return trace

    # ---- 【包：封/拆】（内置 SHA-256 防篡改完整性校验）与【令：视/调/拒/损】 ----
    def op_bao_feng(self, keys: List[str]) -> str:
        """【包·封】：将指定寄存器序列化并附上 SHA-256 完整性哈希签名"""
        payload = {k: self.op_qu(k) for k in keys}
        canonical_body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()
        capsule = {"payload": payload, "sha256": digest}
        return json.dumps(capsule, ensure_ascii=False, sort_keys=True)

    def op_bao_chai(self, packet_str: str) -> Dict[str, Any]:
        """【包·拆】：强制校验 SHA-256 签名，若被篡改立即拉起【立断】拒绝解包！"""
        capsule = json.loads(packet_str)
        if not isinstance(capsule, dict) or not isinstance(capsule.get("payload"), dict):
            self.carry_break_flag = True
            raise ValueError("包·拆 格式错误：胶囊必须是含 payload 字典与 sha256 字段的 JSON 对象！")
        payload = capsule["payload"]
        expected_sha = capsule.get("sha256", "")
        canonical_body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        actual_sha = hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()
        if actual_sha != expected_sha:
            self.carry_break_flag = True
            raise ValueError("包·拆 完整性校验失败：胶囊 SHA-256 签名不匹配，疑似遭到篡改！")
        for k, v in payload.items():
            self.op_cun(k, v)
        return payload

    def define_ling_api(
        self,
        api_name: str,
        shi: str,
        diao_target: str,
        diao_guard: Callable[[Any], bool],
        ju_rule: Callable[[Any], bool],
        sun_handler: Callable[["JianRuntimeVM", Any], Any],
    ) -> None:
        self.apis[api_name] = {
            "视": shi,
            "调": diao_target,
            "准入": diao_guard,
            "拒": ju_rule,
            "损": sun_handler,
        }

    def call_ling_api(self, api_name: str, caller_arg: Any) -> Tuple[str, Any]:
        api = self.apis.get(api_name)
        if not api or api["视"] == "不可":
            return ("隐身不可见(视:不可)", None)
        if api["拒"](caller_arg):
            return ("栈帧前拦截(令·拒)", None)
        if not api["准入"](caller_arg):
            degraded = api["损"](self, caller_arg)
            return ("触发折损降级(令·损)", degraded)
        api["损"](self, caller_arg)
        target_proj = api["调"]
        task_name = self.projs.get(target_proj, target_proj)
        res = self.tasks[task_name](self, caller_arg, False)
        return ("契约调用成功(令·调)", res)

    # ========================================================================
    # 4. 轻量级《简》源码文本解析执行器（直接解析运行《简》源码字符串）
    # ========================================================================
    def execute_jian_source(self, source_code: str) -> List[Any]:
        """
        支持直接解析并执行《简》核心源码（含 // 行注释、定 [...] 返 置/式/判、事 [...] 去 取 [...] 去 判 [...] 分支及 行[显]）。
        Fail-Closed：无法识别的语句行直接抛出 ValueError（附行号），不再静默跳过。
        分支链语义：若 = IF、非若 = ELIF（仅前序分支均未命中时才判定）、否 = ELSE（前序分支均未命中时执行）。
        """
        lines: List[Tuple[int, str]] = []
        for lineno, raw_line in enumerate(source_code.splitlines(), start=1):
            clean = raw_line.split("//")[0].strip()
            if clean:
                lines.append((lineno, clean))

        idx = 0
        while idx < len(lines) and not self.halted:
            lineno, line = lines[idx]

            # 1. 定 [名:类型(:视)] 返 / <- 置 [...] 或 式[...] 或 (实 大 0)
            m_ding = re.match(r"^定\s*\[([^:\]]+)(?::([^:\]]+))?(?::(可|不可))?\]\s*(?:返|<-|=)\s*(.+)$", line)
            if m_ding:
                name, r_type, r_vis, rhs = (
                    m_ding.group(1).strip(),
                    (m_ding.group(2) or "数").strip(),
                    (m_ding.group(3) or "可").strip(),
                    m_ding.group(4).strip(),
                )
                if rhs.startswith("置") or rhs.startswith("=["):
                    inner = re.search(r"\[(.*)\]", rhs)
                    vals = [
                        WavefrontFormulaEngine._resolve_atom(x.strip(), self.formula_env())
                        for x in (inner.group(1).split(",") if inner else [])
                        if x.strip()
                    ]
                    if r_type != "目" and len(vals) != 1:
                        raise ValueError(f"第 {lineno} 行：非【目】类型的 置 [...] 必须恰好给出 1 个值：{line!r}")
                    self.op_cun(name, vals if r_type == "目" else vals[0], r_type, vis=r_vis)
                elif rhs.startswith("式[") or rhs.startswith("$["):
                    val = WavefrontFormulaEngine.eval_expr(rhs, self.formula_env())
                    self.op_cun(name, val, r_type, vis=r_vis)
                elif r_type == "判":
                    # 判 类型保存谓词源码，留待 事 管线中逐个载荷（实）求值；括号交由 式 引擎解析
                    self.op_cun(name, rhs, "判", vis=r_vis)
                else:
                    val = WavefrontFormulaEngine.eval_expr(rhs, self.formula_env())
                    self.op_cun(name, val, r_type, vis=r_vis)
                idx += 1
                continue

            # 2. 事 [事务名] 去/-> 取 [源:类型] 去/-> 判 [规] 及后续 若/非若/否 【执行块】
            m_shi = re.match(
                r"^事\s*\[([^\]]+)\]\s*(?:去|->|→)\s*取\s*\[([^:\]]+)(?::[^\]]+)?\]\s*(?:去|->|→)\s*判\s*\[([^\]]+)\]$",
                line,
            )
            if m_shi:
                evt_name, src_name, pred_name = m_shi.group(1).strip(), m_shi.group(2).strip(), m_shi.group(3).strip()
                src_data = self.op_qu(src_name)
                pred_expr = self.op_qu(pred_name)
                if not isinstance(pred_expr, str):
                    raise ValueError(f"第 {lineno} 行：判 [{pred_name}] 未定义为【判】谓词：{line!r}")
                items = src_data if isinstance(src_data, list) else [src_data]
                all_ok = all(
                    bool(WavefrontFormulaEngine.eval_expr(pred_expr, self.formula_env({"实": item})))
                    for item in items
                )
                outcome = "成" if all_ok else "败"

                idx += 1
                branch_taken = False
                seen_if = False
                while idx < len(lines) and lines[idx][1].startswith(("若", "非若", "否")):
                    b_lineno, b_line = lines[idx]
                    block_match = re.search(r"(?:【|@\{)(.+)(?:】|\})", b_line)
                    block_body = block_match.group(1).strip() if block_match else ""
                    m_cond = re.match(r"^(非若|若)\s*\[([^\]]+)\]", b_line)
                    if b_line.startswith("否"):
                        if not seen_if:
                            raise ValueError(f"第 {b_lineno} 行：否 分支前缺少 若 分支：{b_line!r}")
                        matched = not branch_taken
                    elif m_cond is None:
                        raise ValueError(f"第 {b_lineno} 行：分支条件须写作 若 [成] / 非若 [败]：{b_line!r}")
                    elif m_cond.group(1) == "若":
                        if seen_if:
                            break  # 新的 若 不属于本 事 的分支链，交还外层继续解析
                        seen_if = True
                        matched = m_cond.group(2).strip() == outcome
                    else:
                        if not seen_if:
                            raise ValueError(f"第 {b_lineno} 行：非若 分支前缺少 若 分支：{b_line!r}")
                        matched = (not branch_taken) and m_cond.group(2).strip() == outcome
                    if matched:
                        branch_taken = True
                        if block_body:
                            self._exec_action_block(block_body, evt_name, b_lineno)
                    idx += 1
                    if b_line.startswith("否"):
                        break  # 否 是分支链终点
                continue

            # 3. 取 [名] 去/-> 行 [显]
            m_xian = re.match(r"^取\s*\[([^\]]+)\]\s*(?:去|->|→)\s*(?:行|\$>)\s*\[显\]$", line)
            if m_xian:
                val = self.op_qu(m_xian.group(1).strip())
                self.console_out.append(val)
                idx += 1
                continue

            raise ValueError(f"Fail-Closed 语法错误：第 {lineno} 行无法解析：{line!r}")
        return self.console_out

    def _exec_action_block(self, block_body: str, default_evt: str, lineno: int = 0) -> None:
        for stmt in [s.strip() for s in block_body.split(",") if s.strip()]:
            m_st = re.match(r"^态\[([^:\]]+):([^\]]+)\]$", stmt)
            if m_st:
                self.set_state_keychain(m_st.group(1).strip(), m_st.group(2).strip())
                continue
            m_cun = re.match(r"^存\s*\[([^\]]+)\]\s*(?:自|<-:|from)\s*\[([^\]]+)\]$", stmt)
            if m_cun:
                dst, src = m_cun.group(1).strip(), m_cun.group(2).strip()
                self.op_cun(dst, self.op_qu(src), self.types.get(src, "目"))
                continue
            m_fei = re.match(r"^废\s*\[([^\]]+)\]$", stmt)
            if m_fei:
                self.op_fei(m_fei.group(1).strip())
                continue
            m_gui = re.match(r"^归\s*\[([^\]]+)\]$", stmt)
            if m_gui:
                self.op_gui(m_gui.group(1).strip())
                continue
            if stmt in ("止", "立断"):
                self.carry_break_flag = True
                return
            if stmt in ("结", "立结"):
                self.halted = True
                return
            raise ValueError(f"Fail-Closed 语法错误：第 {lineno} 行执行块内无法解析的语句：{stmt!r}")


# ============================================================================
# 5. 自检测试套件
# ============================================================================

def run_self_tests() -> Dict[str, Any]:
    # 回归测试 A：验证编码器单一事实源、!!brk -> 0x57 与未知算子 Fail-Closed 报错
    assert encode_opcode("定") == 0x00
    assert encode_opcode("断") == 0x17
    assert encode_opcode("立断") == 0x57
    assert encode_opcode("!!brk") == 0x57, f"Expected 0x57, got {hex(encode_opcode('!!brk'))}"
    assert encode_opcode("!!find") == 0x5F
    fail_closed_triggered = False
    try:
        encode_opcode("不存在的乱码算子")
    except ValueError:
        fail_closed_triggered = True
    assert fail_closed_triggered is True, "未知算子必须触发 Fail-Closed 异常！"

    # 回归测试 B：直接把《简》源码文本喂入 execute_jian_source 解析执行！
    vm_src = JianRuntimeVM()
    sample_source = """
    // 示例 1 标准《简》源码直接解析执行测试
    定 [源:目] 返 置 [10, 20, 30]
    定 [密匙:数:不可] 返 9999
    定 [规:判] 返 (实 大 0)

    事 [甲] 去 取 [源:目] 去 判 [规]
      若 [成]   去 则 【 态[甲:真], 存 [甲] 自 [源] 】
      非若 [败] 去 则 【 废 [甲], 止 】
      否        通 去 【 归 [甲] 】

    取 [甲] 去 行 [显]
    """
    console_res = vm_src.execute_jian_source(sample_source)
    assert console_res == [[10, 20, 30]]
    assert vm_src.check_state_keychain("甲", "真") is True
    # 验证数据面零信任：【寻】绝不能搜出标记为 :不可 的 [密匙]
    assert "密匙" not in vm_src.op_xun(9999)
    # 边界说明（v0.9 现行语义，v1.0 设计议题）：视:不可 只防内容寻址扫描，不防按名直读
    assert vm_src.op_qu("密匙") == 9999

    # 回归测试 C：式[...] 双模公式 + 相邻同波次算子最左结合律（1 先减 2 先减 3 == -4）
    env = {"x甲": 7.0, "x乙": 5.0, "乙": 3.0, "戊": 2.0}
    wave_formula = "式[x甲 先先减 乙 后幂 2 后后增 x乙 先先减 乙 后幂 2 后后后商 2 后乘 戊 先先幂 2]"
    sym_formula  = "式[((x甲 - 乙) ^ 2 + (x乙 - 乙) ^ 2) / (2 * (戊 ^ 2))]"
    res_wave = WavefrontFormulaEngine.eval_expr(wave_formula, env)
    res_sym  = WavefrontFormulaEngine.eval_expr(sym_formula, env)
    res_left_assoc = WavefrontFormulaEngine.eval_expr("式[1 先减 2 先减 3]", {})
    assert abs(res_wave - 2.5) < 1e-9 and abs(res_sym - 2.5) < 1e-9
    assert res_left_assoc == -4, f"1 先减 2 先减 3 应按最左结合得 -4，实得 {res_left_assoc}"

    # 回归测试 D：自愈调度器恢复 + 互斥活锁（Livelock）自动触发【立结】检测
    vm = JianRuntimeVM()
    vm.op_cun("甲", 1, "数")
    vm.op_cun("乙", 1, "数")
    vm.op_cun("丙", 0, "数")
    vm.register_fa_xiang_gang(
        "甲",
        fa_fn=lambda v, _: (v.op_qu("甲") % 2 == 0),
        xiang_fn=lambda v, _: v.op_cun("乙", v.op_qu("乙") + 1),
    )
    vm.register_fa_xiang_gang(
        "乙",
        fa_fn=lambda v, _: (v.op_qu("乙") % 2 == 1),
        xiang_fn=lambda v, _: (
            v.op_cun("丙", v.op_qu("丙") + 1),
            v.op_cun("甲", v.op_qu("甲") + 1),
        ),
    )
    sched_trace = vm.run_self_healing_scheduler("甲纲", "乙纲", max_cycles=3)
    assert sched_trace[0][1] == "立断->XCHG重排" and sched_trace[1][1] == "成->顺行"

    # 测试互斥活锁（甲=1 奇无法过甲法，乙=2 偶无法过乙法 -> 正反两序连续立断 -> 自动触发【活锁熔断->立结】）
    vm_livelock = JianRuntimeVM()
    vm_livelock.op_cun("甲", 1, "数")
    vm_livelock.op_cun("乙", 2, "数")
    vm_livelock.register_fa_xiang_gang(
        "甲",
        fa_fn=lambda v, _: (v.op_qu("甲") % 2 == 0),
        xiang_fn=lambda v, _: v.op_cun("乙", v.op_qu("乙") + 1),
    )
    vm_livelock.register_fa_xiang_gang(
        "乙",
        fa_fn=lambda v, _: (v.op_qu("乙") % 2 == 1),
        xiang_fn=lambda v, _: v.op_cun("甲", v.op_qu("甲") + 1),
    )
    livelock_trace = vm_livelock.run_self_healing_scheduler("甲纲", "乙纲", max_cycles=6)
    assert vm_livelock.halted is True and livelock_trace[-1][1] == "活锁熔断->立结"

    # 回归测试 E：读集覆盖【项】自身读取 + op_ti (替) 递增 epoch 触发 CAS 阻断
    vm_cas = JianRuntimeVM()
    vm_cas.op_cun("甲", 2, "数")     # 偶数，【法】校验通过
    vm_cas.op_cun("乙", 10, "数")    # 【法】不读乙，仅【项】自身读取乙并欲令乙+1
    ep_before_ti = vm_cas.epochs["乙"]
    vm_cas.op_ti("乙", 10)           # 验证 op_ti 必须递增 epoch！
    assert vm_cas.epochs["乙"] == ep_before_ti + 1, "op_ti (替) 必须递增 epoch！"

    vm_cas.register_fa_xiang_gang(
        "敏",
        fa_fn=lambda v, _: (v.op_qu("甲") % 2 == 0),
        xiang_fn=lambda v, _: v.op_cun("乙", v.op_qu("乙") + 1),
        # 在【敏项】读取了 [乙] 之后、提交之前，并发调用 op_ti("乙", 99) 抢改 [乙]！
        during_xiang_read_hook=lambda v: v.op_ti("乙", 99),
    )
    xiang_read_conflict_committed = vm_cas.tasks["敏项"](vm_cas, None, False)
    assert xiang_read_conflict_committed is False, "【项】自身读取的数据被 op_ti 并发抢改时必须阻断提交！"
    assert vm_cas.op_qu("乙") == 99, "被阻断的【项】严禁覆盖并发新值！"

    # 回归测试 F：【包·封 / 包·拆】SHA-256 防篡改校验
    capsule = vm.op_bao_feng(["甲", "乙", "丙"])
    tampered_capsule = capsule.replace('"丙": 1', '"丙": 999')
    tamper_caught = False
    try:
        vm.op_bao_chai(tampered_capsule)
    except ValueError:
        tamper_caught = True
    assert tamper_caught is True, "篡改后的胶囊必须被 SHA-256 校验拦截！"

    # 回归测试 G（2026-11-01 修复）：式 引擎——负数中间值、一元负号、科学计数法、括号失配与未定义标识符
    E = WavefrontFormulaEngine
    assert E.eval_expr("式[(1 - 3) * 2]", {}) == -4, "括号内负数中间值不得死循环/误算"
    assert E.eval_expr("式[-3 + 5]", {}) == 2
    assert E.eval_expr("式[2 * -3]", {}) == -6
    assert E.eval_expr("式[-2 ^ 2]", {}) == -4
    assert E.eval_expr("式[2 ^ -1]", {}) == 0.5
    assert E.eval_expr("式[1 - -2]", {}) == 3
    assert abs(E.eval_expr("式[(0.00001 * 1) + 1]", {}) - 1.00001) < 1e-12
    assert E.eval_expr("式[(10 - 30) 先减 1]", {}) == -21
    assert E.eval_expr("式[十 增 二]", {}) == 12
    assert E.eval_expr("式[(1 小 2) 等 真]", {}) is True
    # 乘方右结合；波次前缀算子仍最左结合
    assert E.eval_expr("式[2 ^ 3 ^ 2]", {}) == 512
    assert E.eval_expr("式[2 ** 3 ** 2]", {}) == 512 and E.eval_expr("式[2 幂 3 幂 2]", {}) == 512
    assert E.eval_expr("式[2 先幂 3 先幂 2]", {}) == 64
    assert E.eval_expr("式[2 ^ 3 ^ -1]", {}) == 2 ** (3 ** -1)
    assert E.eval_expr("式[2 ^ -3 ^ 2]", {}) == 2 ** -(3 ** 2)
    # 混调优先级：波次 rank 恒先于符号默认 rank
    assert E.eval_expr("式[x甲 ^ 乙 - 2]", {"x甲": 10, "乙": 3}) == 998
    assert E.eval_expr("式[x甲 ^ 乙 先减 2]", {"x甲": 10, "乙": 3}) == 10
    assert E.eval_expr("式[1 + 2 后乘 3]", {}) == 9 and E.eval_expr("式[1 + 2 * 3]", {}) == 7
    formula_errors_caught = 0
    for bad in ("式[(1 + 2]", "式[1 + 2)]", "式[1 +]", "式[* 2]", "式[1 2]", "式[1 + 未定义量]", "式[()]", "式[1 = 2]"):
        try:
            E.eval_expr(bad, {})
        except ValueError:
            formula_errors_caught += 1
    assert formula_errors_caught == 8, "畸形算式必须 Fail-Closed 抛出 ValueError"
    # 规范示例 2 模式 B：判 谓词内嵌 式[...] 混调
    mode_b = "(实 大 式[(x甲 先减 乙 后幂 2) + ((x乙 - 乙) ^ 2) / (2 后乘 戊 先幂 2)])"
    assert E.eval_expr(mode_b, {**env, "实": 17.0}) is True
    assert E.eval_expr(mode_b, {**env, "实": 16.0}) is False

    # 回归测试 H：编码器覆盖同槽位成员字（< <= >= == != 小/等/大等/小等/非等 -> 0x3A；& 合 -> 0x3B）
    for tok in ("<", "<=", ">=", "==", "!=", "小", "等", "大等", "小等", "非等", ">", "gt"):
        assert encode_opcode(tok) == 0x3A, f"{tok} 应编码为 0x3A"
    assert encode_opcode("&&") == 0x3B and encode_opcode("合") == 0x3B
    assert encode_opcode("立小等") == 0x7A and encode_opcode("成") == 0x3D

    # 回归测试 I：【立项】独占锁——持锁事务自身可写目标寄存器，外部并发写被拒，且锁在结束后释放
    vm_lock = JianRuntimeVM()
    vm_lock.op_cun("甲", 2, "数")
    vm_lock.op_cun("乙", 10, "数")
    external_write_rejected: List[bool] = []

    def _external_writer(v: JianRuntimeVM) -> None:
        try:
            v.op_cun("乙", 777)
            external_write_rejected.append(False)
        except RuntimeError:
            external_write_rejected.append(True)

    vm_lock.register_fa_xiang_gang(
        "锁",
        fa_fn=lambda v, _: (v.op_qu("甲") % 2 == 0),
        xiang_fn=lambda v, _: v.op_cun("乙", v.op_qu("乙") + 1),
        lock_targets=["乙"],
        during_xiang_read_hook=_external_writer,
    )
    lixiang_committed = vm_lock.tasks["锁项"](vm_lock, None, True)
    assert lixiang_committed is True and vm_lock.op_qu("乙") == 11, "【立项】持锁者必须能提交自身写入"
    assert external_write_rejected == [True], "【立项】期间外部写入必须被独占锁拒绝"
    assert not vm_lock.exclusive_locks and not vm_lock._held_locks, "【立项】结束后必须释放锁"

    # 回归测试 J：【项】内的 替/废/归 同样进入写缓冲，事务被阻断时不得泄漏半提交状态
    vm_atomic = JianRuntimeVM()
    vm_atomic.op_cun("甲", 2, "数")
    vm_atomic.op_cun("阈", 0.1, "数")
    vm_atomic.op_cun("旧", 5, "数")
    vm_atomic.register_fa_xiang_gang(
        "原",
        fa_fn=lambda v, _: (v.op_qu("甲") % 2 == 0),
        xiang_fn=lambda v, _: (v.op_ti("阈", 0.5), v.op_fei("旧"), v.op_qu("甲")),
        during_xiang_read_hook=lambda v: v.op_cun("甲", 4),   # 外部篡改读集 -> 本事务必须整体回滚
    )
    atomic_committed = vm_atomic.tasks["原项"](vm_atomic, None, False)
    assert atomic_committed is False
    assert vm_atomic.op_qu("阈") == 0.1 and vm_atomic.lifecycle["旧"] == "存", "被阻断事务内的 替/废 不得落盘"

    # 回归测试 K：源码执行器——否(ELSE) 在前序分支未命中时执行；非若 为 ELIF；未知语句 Fail-Closed
    vm_else = JianRuntimeVM()
    vm_else.execute_jian_source("""
    定 [源:目] 返 置 [10, -5]
    定 [规:判] 返 (实 大 0)
    事 [甲] 去 取 [源:目] 去 判 [规]
      若 [成]   去 则 【 态[甲:真], 存 [甲] 自 [源] 】
      否        通 去 【 存 [乙] 自 [源] 】
    取 [乙] -> $> [显]
    """)
    assert vm_else.console_out == [[10, -5]], "否 分支必须在 若 未命中时执行"
    vm_elif = JianRuntimeVM()
    vm_elif.execute_jian_source("""
    定 [源:目] 返 置 [1]
    定 [规:判] 返 (实 大 0)
    事 [甲] 去 取 [源:目] 去 判 [规]
      若 [成]   去 则 【 存 [甲] 自 [源] 】
      非若 [成] 去 则 【 存 [乙] 自 [源] 】
      否        通 去 【 存 [丙] 自 [源] 】
    """)
    assert "甲" in vm_elif.registers and "乙" not in vm_elif.registers and "丙" not in vm_elif.registers, \
        "若 命中后 非若/否 均不得执行"
    unknown_stmt_rejected = False
    try:
        JianRuntimeVM().execute_jian_source("定 [甲] 返 1\n胡言乱语 [甲]")
    except ValueError:
        unknown_stmt_rejected = True
    assert unknown_stmt_rejected, "无法识别的源码行必须 Fail-Closed"
    # 式 求值经由 op_qu：被【废】的寄存器不得在算式中被脏读
    vm_dirty = JianRuntimeVM()
    vm_dirty.op_cun("甲", 1)
    vm_dirty.op_fei("甲")
    dirty_read_blocked = False
    try:
        vm_dirty.execute_jian_source("定 [乙] 返 式[甲 + 1]")
    except RuntimeError:
        dirty_read_blocked = True
    assert dirty_read_blocked, "式 不得绕过【废】脏读拦截"

    return {
        "status": "ALL_TESTS_PASSED",
        "version": "0.9.0-DualMode",
        "opcode_coverage": {
            "implemented_count": len(IMPLEMENTED_OPCODES),
            "spec_only_count": len(SPEC_ONLY_OPCODES),
        },
        "bugfixes_verified": {
            "op_ti_increments_epoch": True,
            "encode_preempt_brk_0x57": hex(encode_opcode("!!brk")),
            "unknown_opcode_fail_closed": fail_closed_triggered,
            "xiang_own_read_set_protected": (not xiang_read_conflict_committed),
            "scheduler_livelock_halted": vm_livelock.halted,
            "wavefront_left_associative": (res_left_assoc == -4),
            "capsule_sha256_tamper_rejected": tamper_caught,
            "source_text_parser_output": console_res,
        },
        "fixes_2026_11_01_verified": {
            "formula_negative_unary_scientific": True,
            "pow_right_associative_2^3^2": E.eval_expr("式[2 ^ 3 ^ 2]", {}),
            "formula_malformed_fail_closed": formula_errors_caught,
            "encoder_family_members_0x3A": hex(encode_opcode("<=")),
            "lixiang_holder_can_commit": lixiang_committed,
            "lixiang_external_write_rejected": external_write_rejected == [True],
            "xiang_ti_fei_buffered_and_rolled_back": not atomic_committed,
            "source_else_branch_output": vm_else.console_out,
            "source_unknown_stmt_fail_closed": unknown_stmt_rejected,
            "formula_dirty_read_blocked": dirty_read_blocked,
        },
        "self_healing_trace": sched_trace,
        "livelock_halt_trace": livelock_trace,
    }


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run_self_tests()
    print(json.dumps(report, ensure_ascii=False, indent=2))
