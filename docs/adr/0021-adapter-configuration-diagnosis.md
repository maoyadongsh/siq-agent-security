# ADR-021：平台接入配置诊断与运行验证分离

- 日期：2026-09-10。
- 状态：实施中；UX-002、UX-006、UX-012 的接入诊断增量。

## 问题与决定

旧 `adapterinstall.Status` 检查一个插件入口文件便返回 installed，HTTP 平台表据此显示 L2。插件不完整、未在宿主启用、连接其他端口或持有旧配置时也可能显示“仅工具层拦截”。该事实强度不能证明保护已生效。

新增只读 `GET /v1/adapter/diagnostics`（admin 会话），返回 `local-adapter-diagnostics/v1`。每个平台分别列出文件、宿主登记、服务连接配置和运行验证状态；所有诊断只读取有界常规文件，不执行插件、不读取 token 内容、不打印配置正文。目录检查拒绝用户 Home 及以下符号链接，特殊文件和超过 1 MiB 的文件。

- 文件检查将当前安装内容与二进制内嵌适配器摘要比较。相同只证明文件匹配；不同显示版本或内容变化，不能直接推定恶意。旧名安装单独标记，不能误认成已验证的新版本。
- OpenClaw 验证 plugins 的全局开关、allow/deny、load.paths、entry.enabled，及产品配置中的 endpoint/tokenPath/mode 与当前 daemon 是否一致。仅读取精确字段；未识别结构报告检查失败，不推测宿主实际加载情况。
- Hermes 的文件和产品 config.json 可验证；宿主 YAML 中 plugins.enabled/disabled 的解释交由原生平台验证，Go 不用正则或不完整 YAML 解析器赋予“已加载”结论。页面给出原生 `hermes plugins enable siq-agent-security` 及重启会话的下一步，当前仍需用户在正确 profile 执行。后续配置预览与受控接入任务继续实现原生登记和恢复。
- CodeBuddy 的 PreToolUse/PostToolUse 结构按精确产品命令检查，不能用无关字段中出现同名文本代替。
- WorkBuddy 独立返回尚未验证；不能继承 CodeBuddy 的接入结果。Trae 保留无工具钩子的既有范围。
- 运行状态本增量只返回 `unverified`，不产生 effective 权限或新的自检成功记录。真实调用、执行前拒绝、版本绑定与失效处理由后续 UX-006 的原生自检协议完成；回执存在本身也不证明宿主执行过拒绝。

平台 HTTP 响应兼容保留 name/detected/adapter/tier/note，并附可选 diagnosis。未有当前实例原生验证时不再用文件存在将 tier 提升为 L2；UI 优先展示“配置待修复”“配置已就绪，待运行验证”等具体状态。CLI 旧 `adapter status` 的 installed 含义仍是文件存在，文档明确其证据范围，避免破坏已有脚本。

配置诊断不修改用户平台，不自动修复、安装或重启；不能把在测试 Home 的正常/拒绝用例提升为用户现有实例已保护。无需外网、付费模型或宿主进程重启即可进行本项只读诊断。

## 验证

包括完整安装、缺入口、内容变化、插件禁用或缺少登记、其他进程端口/状态目录/模式、符号链接、特殊文件、超大配置、无关字符串假钩子、决策凭据访问拒绝、UI 不再把文件标记当作 L2。保存合同样例及隔离浏览器证据。真实平台自检另登记证据，不能由这些检查代替。

依据：当前本机 Hermes 原生加载器 `_get_enabled_plugins` / `_get_disabled_plugins`；[Hermes 插件说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/built-in-plugins)、[OpenClaw 插件配置](https://docs.openclaw.ai/plugins)，查阅日期 2026-09-10。
