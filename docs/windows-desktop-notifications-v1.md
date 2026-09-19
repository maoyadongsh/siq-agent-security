# Windows 后台通知与待办导航增量

2026-09-18；实现依据为 ADR-032、Win-P04/A09 和既有 UX-008 调度器。此前 Windows 没有默认后台通知器，浏览器通知不覆盖关闭页面后的提醒。本增量接通既有 `desktop_notify=true` 的 Windows 用户桌面路径，默认仍关闭，不更改其他系统通知方式。

## 投递与生命周期

Windows 后端仅用 Go 标准库和 `_windows.go` 内的 Win32 调用，创建本进程专属隐藏顶层消息窗口及通知区图标；使用 `Shell_NotifyIconW`，不安装第三方包，不运行 PowerShell，不注册协议、服务、计划任务或自启项，不更改系统通知/防护设置。窗口线程固定到一个 OS 线程，图标和回调只属于该通知器。创建失败、无交互式桌面或 Shell 不可用时分类失败，既有待办页和工具裁决不受影响。Explorer 的 TaskbarCreated 消息只恢复本进程图标，不重放旧待办通知。

通知只接受固定产品标题和正整数计数句，不发送工具、参数、账号、路径、请求 ID、token 或结果。遵守系统 quiet time，不强制显示。Shell 接受通知请求不等于用户已经看到通知；真实桌面展示和点击证据另行验收。通知发起有界，失败按既有 15 秒合并窗口退避。Explorer 图标恢复失败时保留待恢复状态，每 15 秒重试；重复广播或新通知不能绕过退避，成功或关闭后停止重试，不重放气泡。每次 Windows daemon 启动先等待 15 秒后才允许首次提醒，以免服务连续重启立即重复打扰；不新增持久状态或把通知时序写入审计/授权。

通知器惰性创建：仅选择默认配置不会创建窗口或图标。关闭 dispatcher 时先取消轮询并关闭本通知器，删除精确图标、销毁本窗口和消息线程；不操作其他应用窗口/进程。配置覆盖命令仍优先，沿用原有无 shell、5 秒上限和分类日志规则。

## 点击只导航

点击通知或以键盘选择本通知区图标时，只用 `ShellExecuteW` 打开固定的 `http://127.0.0.1:<当前已监听端口>/confirmations`。端口由 daemon 的已验证配置提供，范围为 1–65535；无任意 URL、路径、命令、查询参数或凭据输入。窗口消息不得修改目标或提供命令参数。关闭后拒绝新投递与点击动作。

该导航不携带配对码/token，不调用任何批准、拒绝、部署或恢复接口。管理身份仍由现有页面配对和会话验证；有多个待办时打开当前实例的列表。浏览器提醒的开启偏好与 daemon `desktop_notify` 是两项已有独立设置，不隐式互相开启。

## 验证边界

实现阶段补充固定 URL、计数隐私、无效目标、退出清理、重启冷却和失败退避的正负向检查；Windows 系统展示、点击和通知拒绝后的 inbox 使用在功能集成后集中实测。不得用 API 返回值或模拟消息把真实桌面条目标为通过。不得为测试重启或注销 Windows。

官方 API 依据：[Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw)、[NOTIFYICONDATAW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw)、[ShellExecuteW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew)。
