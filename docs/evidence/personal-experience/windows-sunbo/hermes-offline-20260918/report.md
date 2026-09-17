# Hermes 原生 Windows 离线拒绝证据

真实安装虚拟环境的 `python -s -B -m hermes_cli.main chat` 使用新私有 profile、固定本地模型响应以及候选 `47ad847fd74c60a23b5714c1f4be98ec1ad518aa` 的原始 SIQ 插件。没有启动桌面或调用付费模型。

## 实际结果与退出码

真实工具结果包含 SIQ `decision service unavailable (no response); blocked (fail-closed)`。审计观察到对专用不监听端口的两次连接尝试，模型服务收到唯一工具结果。没有工具执行子进程，没有输出文件，workspace 空。guard 未拒绝任何操作，不能把测试保护层拒绝当 SIQ 生效。CLI 及实际 Python 退出0，专用 Job 活跃进程0、无强杀，进程句柄及服务端口全部关闭。

原冻结控制器与 wrapper **退出1**，`B_pass=false` 保留：脚本误继承正向 A 的一次 `bash true` 探针断言，而本次拒绝发生于工具执行前，实测为零次。重新读取原始 provider 请求、guard 事件、结果和资源收尾，按拒绝场景要求零工具子进程核验通过。没有修改原结果，没有重跑宿主刷绿。`summary.json` 同时记录原退出码与纠正后的证据判定。

早期 r1 因旧profile三项白名单拒绝新插件目录，宿主未启动；r2 因旧guard只接受一个端口而在身份握手前退出85。r3分别精确列举唯一插件及其三文件/固定配置，并限定两个控制器拥有的127.0.0.1端口；未扩大到外部网络或任意插件。两次旧失败与清理记录均保留。

## 复现

1. 复用已通过的 r5 原生write_file正向控制框架及其 Job/实际Python身份握手，103个已固定安装文件逐一验证摘要。
2. 创建独占测试根并设置私有ACL；隔离 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、TEMP、HERMES_HOME 与cwd。关闭项目插件、遥测、后台模型、LSP和自动更新。仅启用文件工具与siq-agent-security插件。
3. 将候选原始 `__init__.py`、`plugin.yaml` 放入该profile的插件目录，精确核对摘要。插件配置block、1秒超时，使用无权限的合成token。为决策端口设置Windows独占绑定但不listen。
4. 本地固定provider给出唯一write_file调用，再消费其真实工具结果并结束；不改Hermes dispatcher，不模拟SIQ裁决。
5. 核验固定拒绝消息、实际连接、空workspace、零工具子进程和干净收尾。复核前后所有固定源码、配置及测试保护文件未变。

## 范围

此证据是Windows原生Hermes **CLI**离线拒绝，不能替代桌面或完整接入生命周期。服务从未监听，不覆盖健康SIQ停服、授权正向及恢复；#39仍阻断Windows文件资源授权。故P02-HM-A05-01整项保持not_run，并关联这一已完成子场景。唯一台账仍62/303通过、4失败、8受阻、229未测，另3项系统中断排除。Python audit guard不是OS沙箱。

原始输出留本机，摘要保留其SHA256与插件身份，不发布账号、原始环境或私有路径。
