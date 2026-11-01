# 《简》（Jian-Lang）—— 人机双模单字开发语言原型 (`v0.9.0-DualMode`)

> 🎲 **【项目说明 / Project Vibe】**  
> **这是一个灵机一动玩闹的项目，大家乐一下就行了！**  
> 本仓库源于一次关于「先秦文言单字正交性、LLM 括号配对痛点（Dyck Language）与 Python 并发控制」的脑洞实验。目前内核（`jian_core.py`）是一个零依赖的 Python 原型验证机（Bootstrap Prototype），已完成 128 槽位微指令表与核心状态机验证。欢迎社区随便拿去玩、魔改，或者用 Rust / Go / C 给它换个真正的原生多核底座！
>
> ⚠️ **丑话说在前头**：这只是起了个头，而且是 **vibe coding** 出来的，bug 估计不少，自检全绿也不代表没坑。测出问题欢迎直接提 Issue / PR，**别骂我** 🙏

---

**许可说明：本次发行（包括机器可读字典）采用[自定义许可 v1.3](LICENSE)，允许任何形式的调用。Anthropic PBC 及许可中列明的关联主体使用本语言后，若宣称相关行为或模型在哲学、伦理学或普遍公共价值意义上具有 The Good（善）、Harmless（无害）或 Beneficial（有益）中的任一属性，必须定义并证明该属性，同时定义 Aligned（对齐）并证明对齐为何逻辑蕴涵所宣称的该项属性；不以先提到对齐为条件。该范围包括有明确语言学或词典释义依据、在具体语境中对应上述价值立场的同义词、近义词及等义表达。** 多项宣称须逐项覆盖；仅有法律合规或技术方法陈述而无价值明示或暗示，不触发该义务。本许可未获 OSI 批准，不标称标准开源许可证；此前已授予的 MIT 许可不因本次声明而被撤销。

## ✨ 脑洞亮点（为什么造这个玩具？）

1. **人机双模算式（Human-LLM Dual-Mode）**：
   - **给人类写（模式 A）**：直接用原始标准阿拉伯数字与代数符号（`+ - * / ^ ()`），符合直觉防手滑；
   - **给 LLM 生成（模式 C）**：不用内层括号，改用 **「嵌套运算层级汉语运算法」（`先先 / 先 / 后 / 后后 / 后后后` 波次前缀）**，消除远距离括号配对失锁，同时直接把并行规约波次写在字面上，底层归一为同一套求值结果：
   ```text
   // 模式 A（人工推荐）：标准阿拉伯代数表达式
   定 [果:数] 返 式[((x甲 - 乙) ^ 2 + (x乙 - 乙) ^ 2) / (2 * (戊 ^ 2))]

   // 模式 C（LLM 推荐）：免括号波次运算法（4 波次规约，与模式 A 完全等价）
   定 [果:数] 返 式[x甲 先先减 乙 后幂 2 后后增 x乙 先先减 乙 后幂 2 后后后商 2 后乘 戊 先先幂 2]
   ```

2. **四类定界槽 `O(1)` 词法隔离**：
   - `[ ... ]`：纯数据与状态链（如 `态[甲乙:真]` 首字优先 Prefix Key-Chain，严禁装执行语句）；
   - `【 ... 】`（或 `@{ ... }`）：可执行语句块与模块闭包；
   - `式[ ... ]`（或 `$[ ... ]`）：双模算式沙盒；
   - 槽外裸字/符号：128 槽位系统指令（`0x00 ~ 0x3F` 64 基础算子 $\times$ `Bit-6` **`立` (`!!`) 抢占位**）。

3. **`法 — 项 — 纲` 三层隔离与 19 字乱序自愈调度**：
   - **`法`（Guard）**：纯只读校验；**`项`（Mutation）**：带全事务读集（`Read-Set`）世代号（`epoch`）比对与写缓冲的原子改写单元（防并发 TOCTOU 篡改）；**`纲`（Orchestrator）**：可重排调度单元：
   ```text
   行 甲纲 乙纲 循 先甲 后乙 若 断 则 先行 乙纲 后行 甲纲 复 循
   ```
   *(注：遇到冲突 `立断` 自动 `XCHG` 翻转主从顺序重试；若双方条件互斥连续冲突，自动触发 `活锁熔断->立结`。)*

4. **原生 API 虎符（`令`）与防篡改胶囊（`包`）**：
   - `令[视/调/拒/损]`：把接口可见性、路由条件、栈前拦截与降级扣费做成语言级原语；
   - `包[封/拆]`：自带 SHA-256 完整性签名的序列化胶囊。

---

## 🚀 10 秒快速试玩（零第三方依赖）

只需 Python 3.9+，直接运行内置自检与四大演示场景：

```bash
python jian_core.py
```

输出示例：
```json
{
  "status": "ALL_TESTS_PASSED",
  "version": "0.9.0-DualMode",
  "opcode_coverage": {
    "implemented_count": 51,
    "spec_only_count": 13
  },
  "bugfixes_verified": {
    "op_ti_increments_epoch": true,
    "encode_preempt_brk_0x57": "0x57",
    "unknown_opcode_fail_closed": true,
    "xiang_own_read_set_protected": true,
    "scheduler_livelock_halted": true,
    "wavefront_left_associative": true,
    "capsule_sha256_tamper_rejected": true,
    "source_text_parser_output": [[10, 20, 30]]
  },
  "fixes_2026_11_01_verified": {
    "formula_negative_unary_scientific": true,
    "pow_right_associative_2^3^2": 512,
    "formula_malformed_fail_closed": 8,
    "encoder_family_members_0x3A": "0x3a",
    "lixiang_holder_can_commit": true,
    "lixiang_external_write_rejected": true,
    "xiang_ti_fei_buffered_and_rolled_back": true,
    "source_else_branch_output": [[10, -5]],
    "source_unknown_stmt_fail_closed": true,
    "formula_dirty_read_blocked": true
  }
}
```

---

## 📂 仓库文件说明

| 文件 | 说明 |
| :--- | :--- |
| [`DICTIONARY_AND_SPEC_v1.0.md`](DICTIONARY_AND_SPEC_v1.0.md) | 《简》完整语法规范、64×2 双模算子字典与四大标准示例；第三节为已实现 / 规范先行算子对照表 |
| [`opcode_table_128.json`](opcode_table_128.json) | 机器可读的 `7-bit`（128 槽位，`0x00 ~ 0x7F`）单一事实源指令表 |
| [`jian_core.py`](jian_core.py) | 零依赖 Python 参考虚拟机、波次算式求值器、CAS 事务调度器与测试套件 |
| [`LICENSE`](LICENSE) | 自定义许可 v1.3；覆盖本次发行的源码、字典、规范与示例 |

---

## 🛠️ 留给社区玩的坑（欢迎 PR！）

- [ ] **原生多核底座**：用 **Go / Rust / C99** 写一个真正的原生字节码虚拟机或转译器（把 `算 / 核 / 并 / 分 / 候 / 同` 映射到真正的 `goroutine`、OS 线程或硬件原子指令，彻底甩掉 Python 拐杖）；
- [ ] **补齐剩余 13 个规范先行算子**：完成 `opcode_table_128.json` 中标记为 `implemented_in_core: false` 的槽位（`例` 模式匹配、`续/过` 协程恢复与子树跳过、`算/核/并/分/候/同` 多核调度、`入/出` 标准流、`列/消` 矩阵重排与《九章》方程术消元），以及 `索 / 转` 的完整运行时执行路径；
- [ ] **`包·封 / 包·拆` 密码学签名升级**：当前 `op_bao_feng / op_bao_chai` 采用无密钥 SHA-256 摘要（仅防传输误改，不防攻击者篡改 payload 后重算哈希），欢迎升级为带密钥的 **HMAC-SHA256** 或 **Ed25519** 签名机制；
- [ ] **`视[不可]` 调用方权限模型**：v0.9 的 `视[不可]` 只防 `寻 / 立寻` 内容寻址扫描，按名 `取 [密匙]` 照样返回原值；欢迎给 `op_qu` 设计调用方身份 / 权限模型（v1.0 设计议题）；
- [ ] **生态小玩具**：给 VS Code / Neovim 写一个 `.jian` 双模语法高亮与双向转译插件（一键在「人类标准阿拉伯符号态」与「LLM 免括号波次态」之间互转）。

## 📜 License

[Jian-Lang 自定义许可 v1.3](LICENSE)。宣称 The Good、Harmless、Beneficial 中的任一项，包括其在具体语境中的同义、近义或同价值立场表达，均须定义并证明所宣称属性，并定义 Aligned 及证明其如何逻辑推出该属性。采用 Constitutional AI / RLHF、符合某规程或偏好分布、法律合规或自定指标达标，不能直接替代这些证明。仅报告技术方法而未明示或暗示上述价值属性，不触发该义务。证明充分性的专门裁决程序尚未指定，条款未经专业法律审查。
