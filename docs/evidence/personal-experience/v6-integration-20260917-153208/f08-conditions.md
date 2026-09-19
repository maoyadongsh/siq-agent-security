# F08 本机条件复核（2026-09-17）

仅运行本机 DNS 解析与 `command -v workbuddy`，未改 DNS/hosts/代理，未发起下载、安装或宿主任务。

| 条件 | 本次可复核事实 | 阶段判定 |
| --- | --- | --- |
| `github.com` | `getent ahostsv4` → `198.18.0.9` | 本机解析落在 198.18/15 保留测试网段；现有托管源 SSRF 门按设计拒绝，不能用放宽私网检查来刷通过。 |
| `raw.githubusercontent.com` | `getent ahostsv4` → `198.18.0.11` | 同上。 |
| `codeload.github.com` | `getent ahostsv4` → `198.18.0.6` | 同上。 |
| WorkBuddy | `command -v workbuddy` 退出 1 | 本机未找到可执行宿主；仓库中的 `workbuddy` hook 合同/夹具不等于真实运行时。 |

因此，F08 本轮仍为 `conditional blocked`。解除条件：在**不改变产品 SSRF 规则**的环境中取得真实公网解析、TLS 与固定来源，使用受控合成来源完成暂存→检查→确认→安装→更新/漂移/失败恢复；WorkBuddy 需真实宿主、版本、原生 hook 接入点和可核验调用链。此检查不沿用旧候选的成功状态，也不代表网络可达性测试已完成。
