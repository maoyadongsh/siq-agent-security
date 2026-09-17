# macOS Luke：独立注销／登录后的隔离状态恢复

在 [P13 真实重启](../p13-20260916-223833/report.md)及 [P16 真实休眠／唤醒](../p16-20260916-225959/report.md)之后，本批另行完成一次**正常注销与重新登录**。注销前 23:01:06 的 console `loginwindow` PID 为 432、GUI ASID 为 100023；通过 System Events 正常请求 `log out`，用户随后重新登录并返回任务。23:21:49 只读检查显示新的 console 登录时间约 23:18、`loginwindow` PID 4266、GUI ASID 100111；`kern.boottime` 前后均为 1789569104（22:31:44），所以这是独立新登录而非重启或仅重开 shell。脱敏断言见 [logout-login.json](logout-login.json)。

同一私有 WorkBuddy 测试状态以受测 Mach-O arm64、CGO=0 二进制读回：`state-status` 的 `format_version=2/compatible=true/status=ok`，`verify --chain local` 的 `verified=true`、22 条、head seq 21、head hash 与注销前一致。受控只读和越权哨兵、日常 WorkBuddy 配置的 SHA256 均未变。隔离 47614 在登录后原本无监听；手动 `serve` 后 `status --port 47614` 返回 `product=siq-agent-security/status=ready/local_mode=true`，随后正常停止，47614/47615 均无监听。工作树检查干净，未触碰日常 WorkBuddy 配置或服务。

**边界：** 这证明正常注销／登录之后现有隔离状态及回执链可读、服务可手动恢复；注销前未注册测试 LaunchAgent，不能推导登录自启或 manager 自动恢复。也不证明断电耐久性、正式签名／公证。Mac-P00–P05 的三宿主审批继续、可信 Skill 来源、原生安装前拦截、通知点击回跳、可追溯旧版拒写和独立审阅仍未通过；Intel/amd64 实机已由用户明确排除本轮范围。无 sudo、全局 PATH 或安全策略变更；没有归档状态私钥、token、配对码、账号／对话原文或绝对用户路径。
