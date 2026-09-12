# Skill 分发兼容性证据（2026-09-12）

本实验只验证固定版本上游 CLI 的本地源码、project / copy 安装与卸载。最终结果为 [attempt-4.json](attempt-4.json)，机器可读索引为 [summary.json](summary.json)。报告按原始字节归档，索引记录每份报告的 SHA-256。

| 尝试 | 结果 | 解释 |
| --- | --- | --- |
| [attempt-1](attempt-1.json) | failed | 测试工具把 add JSON 的 Agent 展示名称误当作命令行枚举。修复解析并增加回归测试；此失败记录保留。 |
| [attempt-2](attempt-2.json) | passed | 四目标复制与卸载通过；工具尚未包含后续补强。仅保留历史，不作为当前工具的实测证明。 |
| [attempt-3](attempt-3.json) | passed | 增加三项 Node 权限负向探针后通过。仍早于最终审阅修复，不作为当前工具的实测证明。 |
| [attempt-4](attempt-4.json) | passed | 最终版本：四目标复制、卸载、无关 Skill 保留及三项权限负向探针均通过；runner、verifier 和 pin 摘要与收口时文件一致。 |

最终实测环境是 macOS（Darwin x86_64）、Python 3.13.3、Node.js v24.21.0。OpenClaw、Hermes Agent、CodeBuddy、Trae 每个安装目标的 28 个文件均与来源一致，包含文件集合、字节数、SHA-256 和 POSIX 可执行位；源树保持原样。

来源是 `1e20635843c0966e24d73d149e3d7bcd080f89c4` 的 `skills/siq-agent-security`，上游为 skills 1.5.26 / `d667282815248da03a08a18272b5d2eef9caf77c`。归档没有重写来源 Skill、manifest 或旧证据。

收口验证：46 项 research 单测通过（36 项分发测试、10 项已有测试），`ruff check scripts/research` 通过；研究元数据检查通过。独立审阅发现的畸形 pin 失败报告缺口已修复并加入主入口负向测试。

Linux/macOS GitHub Actions 已配置，但未在远端运行。四个目标表示上游安装目录兼容，不表示四个原生 Agent 已启动。本实验未执行候选脚本，未验证 runtime enforcement、发布签名或网络隔离，不计入 V5 攻击防护分母，也不构成发布授权。复跑方式与限制见[分发指南](../../skills-distribution.md)。
