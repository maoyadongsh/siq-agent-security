# F08 本机条件复核

2026-09-17 本机 DNS 对 GitHub、codeload、objects 三个来源分别返回 `198.18.0.9`、`198.18.0.6`、`198.18.0.12`，均属 198.18/15 保留段；逐项结果在 [来源预检](hosted-source-preflight.json)。因此本批未发起 TLS、重定向或固定版本下载，不改变 SSRF 私网拒绝、hosts/DNS/代理或 TLS 校验。真实托管源安装、漂移与下载中断验收仍 blocked，解除条件是可信的公共解析与直连网络。

[WorkBuddy 探测](workbuddy-probe.json)以真实用户 HOME 的只读元数据探测运行，`environment_unavailable`：缺 `~/.workbuddy/buddies.json`、可执行程序与运行进程。旁系 `~/.codebuddy` 不当作 WorkBuddy 宿主。诊断脚本已修复隔离 HOME 误继承真实 HOME/PATH/进程的证据污染，并以两个负例覆盖；修复前报告仅留在忽略的 `probe-private/`，新公开报告把真实 HOME 标成 `~`，不公开绝对路径。WorkBuddy 八项宿主验收均未运行，不能以夹具或目录存在标通过。
