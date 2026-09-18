# Mac-P02 起步：隔离 HOME 只读发现与预览

日期：2026-09-15。接续同一实现候选 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`。本文件不是三宿主完整旅程验收。

P01 的管理服务曾使用真实用户 HOME，发现页出现默认宿主资产计数。P02 起改用独立：

- 宿主 HOME：`~/.local/siq-macos-luke-p02-hosts/home`
- SIQ 状态：`~/.local/siq-macos-luke-p02-state`
- `OPENCLAW_STATE_DIR` / `HERMES_HOME` 指向该 HOME 下的夹具目录
- 未设置这些变量的日常 `~/.openclaw`、`~/.hermes`、WorkBuddy 日常配置未作为写入目标

## 夹具内容（无真实账号）

隔离 HOME 内自建：OpenClaw 两个 agent（studio/research）、共享与 workspace Skill 各一；Hermes 默认与 `work` profile、同名 Skill 与 work-only Skill。共 7 个文件。预览前后 SHA256 前缀未变。

## 只读结果

| 检查 | 结果 |
| --- | --- |
| `inventory`（HOME=隔离根） | platforms=`hermes,openclaw`；candidates=10（hermes 5 + openclaw 5）；source_types：hermes_profile 2、openclaw_agent 2、platform_config 2、skill_dir 4；skipped=0 |
| `adapter preview openclaw install` | 退出 0，`local-adapter-plan/v1`，5 个 `create`；隔离 `.openclaw` 文件树未变 |
| `adapter preview hermes install` | 退出 0，`local-adapter-plan/v1`，4 个 `create`；隔离 `.hermes` 文件树未变 |
| WorkBuddy | 未纳入该隔离 HOME。桌面应用仍在 `/Applications`，日常配置未动 |

尚未做：确认安装、真实宿主加载、允许/越权/失联、卸载还原、WorkBuddy 桌面交互。确认安装必须走产品确认路径，且只写上述隔离实例。

续（2026-09-16）：上述缺口中的 OpenClaw/Hermes CLI 链路、卸载还原与 WorkBuddy 只读盘点见 [p02-20260916-000754/report.md](../p02-20260916-000754/report.md)。WorkBuddy 桌面交互仍 blocked。
