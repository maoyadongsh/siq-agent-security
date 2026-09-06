# 能力事实 → 准入 disposition 矩阵 v1（DEV06-F）

合同源：`apps/agentshield/internal/admission/dispositions.go`；锁测：`dispositions_matrix_test.go`。

本表描述 **共享威胁规则** 在可执行区（`scripts/*`）且 **同文件无 egress** 时的 category / disposition / 声明能力。  
`declare` 产出 `state=declared` 权限事实（须人类 grant）；`quarantine` 不产出声明能力；`info` 仅记录。

| rule_id | category | disposition | domain | action | resource |
| --- | --- | --- | --- | --- | --- |
| threat-download-exec-pipe | dangerous_code | declare | process | process.exec | tool=`shell` |
| threat-download-exec-powershell | dangerous_code | declare | process | process.exec | tool=`shell` |
| threat-cred-ssh | credential_exfil | declare | credential | credential.read | `~/.ssh` |
| threat-cred-dotenv | credential_exfil | declare | credential | credential.read | `.env` |
| threat-cred-system-files | credential_exfil | declare | credential | credential.read | `/etc/passwd,/etc/shadow` |
| threat-cred-cloud | credential_exfil | declare | credential | credential.read | cloud CLI homes |
| threat-cred-browser-store | credential_exfil | declare | credential | credential.read | browser store |
| threat-cred-hardcoded-secret | credential_exfil | declare | credential | credential.read | hardcoded-literal |
| threat-persist-crontab | persistence | declare | filesystem | fs.write | crontab paths |
| threat-persist-systemd | persistence | declare | filesystem | fs.write | systemd-units |
| threat-persist-launchd | persistence | declare | filesystem | fs.write | LaunchAgents |
| threat-persist-run-key | persistence | declare | filesystem | fs.write | Run key |
| threat-persist-shell-rc | persistence | quarantine | — | — | — |
| threat-obf-*（4） | dangerous_code | declare | process | process.exec | tool=`shell` |
| threat-net-reverse-shell | credential_exfil | quarantine | — | — | — |
| threat-net-webhook-exfil | credential_exfil | quarantine | — | — | — |
| threat-net-hardcoded-c2 | credential_exfil | declare | network | socket.connect | endpoint（excerpt token） |
| threat-prompt-injection | prompt_injection | quarantine | — | — | —（scripts/ 或非示例 SKILL.md） |
| threat-py-*（4 正则） | dangerous_code | declare | process | process.exec | tool=`shell` |

## 正交判据（不得合并）

| 条件 | 结果 |
| --- | --- |
| 任一 `threat-cred-*` **且** 同文件有 egress | quarantine，**不**产出 declared fact |
| persist excerpt 含 `authorized_keys` | quarantine |
| `docs/`/`references/` 等 **散文** `.md` | 降为 info，清除 capability |
| 同上目录下的 **代码文件**（`.sh`/`.py`/…） | 保留核心 disposition（H5b） |

## 诚实边界

- 本矩阵锁的是 **准入分类器**，不是控制面策略批准或 effective 权限。
- AST 独有 Python 规则（`threat-py-os-system` 等）不在共享 rulepack，不在本表。
- 跨产品 profile 差异、留出集评测未宣称。
