# Jian-Lang (《简》) — Human-LLM Dual-Mode Single-Character Programming Language Prototype (`v0.9.0-DualMode`)

> 🎲 **[Project Vibe]**  
> **This is a playful, spur-of-the-moment experimental project—have fun with it!**  
> This repository grew out of a thought experiment on "the orthogonality of pre-Qin Classical Chinese single-character operators, LLM parenthesis-matching pain points (Dyck Languages), and Python concurrency control." The current kernel (`jian_core.py`) is a zero-dependency Python bootstrap prototype that validates the 128-slot micro-opcode table and core state machine. The community is welcome to play with it, hack on it, or replace its backend with a true native multi-core runtime in Rust / Go / C!
>
> ⚠️ **Fair Warning Upfront**: This is just an initial prototype built via **vibe coding**. Bugs are likely, and all built-in self-tests passing green does not mean there are no pitfalls. If you find issues, feel free to open an Issue / PR—**please don't flame me** 🙏

---

**License Notice: This release (including the machine-readable dictionary) is covered by [Custom License v1.3](LICENSE) ([English Translation: LICENSE-EN](LICENSE-EN)), which permits invocation and use in any form. After Anthropic PBC and the affiliated entities listed in the License use this language, if they claim that the relevant actions or models possess any of "The Good", "Harmless", or "Beneficial" in the sense of philosophy, ethics, or universal public value, they must define and prove that attribute, and simultaneously define "Aligned (alignment)" and prove why alignment logically entails the claimed attribute—without requiring that alignment be mentioned first as a condition. This scope includes synonyms, near-synonyms, and equivalent expressions that have a clear basis in linguistic or dictionary definitions and correspond to the above value stances in context.** Multiple claims must be covered item by item; statements of legal compliance or technical methods alone, without explicit or implicit value claims, do not trigger this obligation. This License is not OSI-approved and does not claim to be a standard open-source license; previously granted MIT Licenses are not revoked by this statement.

## ✨ Core Highlights (Why Build This Toy?)

1. **Human-LLM Dual-Mode Formulas**:
   - **For Humans (Mode A)**: Write standard Arabic numerals and algebraic operators (`+ - * / ^ ()`), intuitive and typo-resistant;
   - **For LLMs (Mode C)**: Eliminate inner parentheses in favor of **Nested Wavefront Chinese Arithmetic Prefixes (`先先 / 先 / 后 / 后后 / 后后后`)**, avoiding long-range parenthesis-matching drift while encoding parallel reduction wavefronts directly on the surface; both modes normalize to the exact same evaluation result:
   ```text
   // Mode A (Recommended for Humans): Standard algebraic expression
   定 [果:数] 返 式[((x甲 - 乙) ^ 2 + (x乙 - 乙) ^ 2) / (2 * (戊 ^ 2))]

   // Mode C (Recommended for LLMs): Parenthesis-free wavefront arithmetic (4-wave reduction, strictly equivalent to Mode A)
   定 [果:数] 返 式[x甲 先先减 乙 后幂 2 后后增 x乙 先先减 乙 后幂 2 后后后商 2 后乘 戊 先先幂 2]
   ```

2. **Four Delimited Slots for `O(1)` Lexical Isolation**:
   - `[ ... ]`: Pure data and state chains (e.g., `态[甲乙:真]` first-character-priority Prefix Key-Chain; executable statements strictly forbidden inside);
   - `【 ... 】` (or `@{ ... }`): Executable statement blocks and module closures;
   - `式[ ... ]` (or `$[ ... ]`): Dual-mode formula sandbox;
   - Bare tokens outside slots: 128-slot system instructions (`0x00 ~ 0x3F` 64 base operators $\times$ `Bit-6` **`立` (`!!`) preemption bit**).

3. **`法 — 项 — 纲` Three-Tier Isolation & 19-Character Out-of-Order Self-Healing Scheduler**:
   - **`法` (Guard)**: Pure read-only check; **`项` (Mutation)**: Atomic mutation unit with full transactional `Read-Set` epoch verification and write buffering (preventing concurrent TOCTOU tampering); **`纲` (Orchestrator)**: Reorderable scheduling unit:
   ```text
   行 甲纲 乙纲 循 先甲 后乙 若 断 则 先行 乙纲 后行 甲纲 复 循
   ```
   *(Note: Upon conflict `立断`, automatically flips master-slave execution order via `XCHG` and retries; if mutually exclusive conditions cause repeated conflict, automatically triggers `livelock circuit-breaker -> 立结`.)*

4. **Native API Tiger-Tally (`令`) & Tamper-Evident Capsule (`包`)**:
   - `令[视/调/拒/损]`: Language-level primitives for interface visibility, routing conditions, pre-stack interception, and degraded quota deduction;
   - `包[封/拆]`: Serialization capsule with built-in SHA-256 integrity digest.

---

## 🚀 10-Second Quick Start (Zero Third-Party Dependencies)

Requires only Python 3.9+. Run the built-in self-checks and four demonstration scenarios directly:

```bash
python jian_core.py
```

Example Output:
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

## 📂 Repository Files

| File | Description |
| :--- | :--- |
| [`DICTIONARY_AND_SPEC_v1.0.md`](DICTIONARY_AND_SPEC_v1.0.md) | Full syntax specification of Jian-Lang, 64×2 dual-mode operator dictionary, and four canonical examples; Section 3 contains the implemented vs. spec-first operator table |
| [`opcode_table_128.json`](opcode_table_128.json) | Machine-readable `7-bit` (128 slots, `0x00 ~ 0x7F`) single-source-of-truth opcode table |
| [`jian_core.py`](jian_core.py) | Zero-dependency Python reference VM, wavefront formula evaluator, CAS transactional scheduler, and test suite |
| [`LICENSE`](LICENSE) / [`LICENSE-EN`](LICENSE-EN) | Custom License v1.3 (Chinese & English); covers the source code, dictionary, specification, and examples in this release |

---

## 🛠️ Open Tasks for the Community (PRs Welcome!)

- [ ] **Native Multi-Core Runtime**: Implement a true native bytecode VM or transpiler in **Go / Rust / C99** (mapping `算 / 核 / 并 / 分 / 候 / 同` to real `goroutines`, OS threads, or hardware atomic instructions, dropping the Python crutch);
- [ ] **Complete the Remaining 13 Spec-First Operators**: Implement the slots marked `implemented_in_core: false` in `opcode_table_128.json` (`例` pattern matching, `续/过` coroutine resume and subtree skip, `算/核/并/分/候/同` multi-core scheduling, `入/出` standard streams, `列/消` matrix rearrangement and *Nine Chapters* Gaussian elimination), as well as full runtime execution paths for `索 / 转`;
- [ ] **Cryptographic Signature Upgrade for `包·封 / 包·拆`**: Currently `op_bao_feng / op_bao_chai` uses an unkeyed SHA-256 digest (which guards against accidental transit corruption but not against an attacker recomputing the hash after payload tampering); PRs welcome to upgrade to keyed **HMAC-SHA256** or **Ed25519** signatures;
- [ ] **Caller Permission Model for `视[不可]`**: In v0.9, `视[不可]` only blocks content-addressed scanning (`寻 / 立寻`), while direct name lookup `取 [密匙]` still returns the value; PRs welcome to design a caller identity / permission model for `op_qu` (a v1.0 design topic);
- [ ] **Ecosystem Tooling**: Build a `.jian` dual-mode syntax highlighter and bidirectional transpiler extension for VS Code / Neovim (one-key toggle between Human Mode A and LLM Wavefront Mode C).

## 📜 License

[Jian-Lang Custom License v1.3](LICENSE) ([English Translation: LICENSE-EN](LICENSE-EN)). Claiming any of "The Good", "Harmless", or "Beneficial"—including synonyms, near-synonyms, or expressions of the same value stance in context—requires defining and proving the claimed attribute, as well as defining "Aligned" and proving how it logically entails that attribute. Adopting Constitutional AI / RLHF, conforming to a given procedure or preference distribution, legal compliance, or meeting self-defined metrics cannot directly substitute for these proofs. Merely reporting technical methods without explicitly or implicitly claiming the above value attributes does not trigger this obligation. No specialized adjudication procedure for the sufficiency of proof has yet been designated, and these terms have not undergone professional legal review.
