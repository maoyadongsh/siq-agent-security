# SIQ Skill Distribution Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the verifier and independent review; root integrates the smoke runner, documentation and CI.

**Goal:** 固定 vercel-labs/skills 的分发验证，不把安装成功提升为安全结论。

**Architecture:** 源/目标目录只读比较器 + 固定 npm 包真实 CLI smoke + 独立证据。生产运行时与 Skill 内容不变。

**Tech Stack:** Python stdlib、Node.js permission、可信 Git、现有 GitHub Actions。

## Task 1: 目录分发验证器

- [x] 新建 `scripts/research/test_verify_skill_distribution.py`，先写正常复制、修改/遗漏/额外文件、文件和目录 symlink、FIFO、大小/深度限额、可执行位、输出覆盖拒绝的测试并确认失败。
- [x] 新建 `scripts/research/verify_skill_distribution.py`。提供 `snapshot_tree(path)`、`verify_distribution(source, installed)`、CLI `--source --installed --out`。只打开普通文件，限长读取，比较前后 stat，报告明确 `distribution_only`。
- [x] `python3 -m unittest discover -s scripts/research -p 'test_verify_skill_distribution.py' -v` 必须通过。

## Task 2: 固定上游并运行真实 CLI

- [x] 新建 `scripts/research/skills-upstream.json`：固定 skills 1.5.26 / d667282815248da03a08a18272b5d2eef9caf77c，填写经官方 registry 取回并核对的 tarball 完整性。
- [x] 新建 `scripts/research/test_skills_distribution_smoke.py`，测试 pin 校验、包摘要不符、archive 路径逃逸与链接拒绝、输出目录占用、环境过滤。
- [x] 新建 `scripts/research/skills_distribution_smoke.py`。明确 `--out-dir`，使用新建目录且失败也写入失败报告。下载后校验摘要再提取，限额普通文件；不运行 npm lifecycle。
- [x] Git archive 固定 source commit；在独立 project 运行上游 CLI 的 list/add/remove，以固定 Agent 名称及 `--copy` 模式逐个验证；禁止任何 Skill 脚本执行。
- [x] 运行 smoke 并归档摘要报告，保留实际失败尝试；修复只涉及测试基础设施，不修改冻结 Skill 以迎合安装器。

## Task 3: 文档与 CI

- [x] 新建 `docs/research/skills-distribution.md`，说明 CLI、证据范围、源码/二进制/钩子的分别准备、已知布局与更新缺口，以及后续实现接口。
- [x] 从 `README.md`、`README.en.md`、`docs/research/README.md` 添加窄范围入口，不改既有发布声明。
- [x] 新增 `.github/workflows/skills-compat.yml`，Actions 引用固定 SHA；先运行离线单测，再运行精确版本 smoke；不自动发布、不扩大现有保护等级。

## Task 4: 审阅与收口

- [x] 运行全部 research 单测、ruff、研究元数据链接检查、Actions pin 检查和 `git diff --check`。
- [x] 独立 reviewer 先检查设计范围与实现，再检查安全性/可维护性；处理可复现的问题后复查。
- [x] 确认 runtime、Skill payload、V5 evidence 未修改；记录分支与实际验证结果。

## 交付记录

2026-09-12：上述任务完成；最终 smoke 为 [attempt-4](../../research/evidence/skills-distribution-20260912/attempt-4.json)，四目标通过。全部 research 单测 46 项通过，ruff、元数据和 Actions pin 检查通过。独立审阅问题已修复并复核。runtime、Skill payload、合同与 V5 evidence 均无修改。

分支 `codex/skills-distribution-20260912` 基于 `1e20635843c0966e24d73d149e3d7bcd080f89c4`。首次交付依 AGENTS.md 保留未提交修改；随后用户在 2026-09-12 明确提出合并 main，授权本地提交与合并，实际提交身份以 Git 历史为准。未触发远端 CI 或发布。

合并前复核修正了相对于新版 main 的文档范围：SIQ 已有目录安装身份、多消费者关联、ZIP 导入与 Hermes 受控安装/更新及逐次 runtime 校验，剩余工作是 Vercel CLI 的衔接。Google Skills 的质量治理借鉴仅作为只读研究记入分发指南，未扩大本轮实现范围。
