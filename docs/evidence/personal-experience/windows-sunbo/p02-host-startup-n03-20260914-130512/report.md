# Windows 宿主启动诊断与共享核心复验

本批追加 Windows 原生 Hermes、WSL2 OpenClaw 启动诊断，以及固定 PR #45 源提交的 Windows 更新检查测试。它不关闭 Windows/P02/P03/N09，也不把宿主启动失败或测试 guard 拒绝计为 SIQ 阻断成功。旧失败记录和候选身份保留。

| 范围 | 已取得的结果 | 限制 |
| --- | --- | --- |
| N03 更新检查 | 3 个顶层测试通过，其中包含 10 个通过子例；0 fail、0 skip | Windows 组件测试，未完成真实宿主安装更新旅程。首次冷缓存超时单独保留，三项当时未执行。 |
| 安装诊断 | 2 个顶层测试通过、1 个失败 | Windows 本来不生成 Hermes shell wrapper，测试读取失败；后续 POSIX 权限和顺序断言未执行。 |
| Hermes Windows | v2–v8 公共 CLI 诊断未完成真实文件写入；B 未运行 | v8 发生 0xC0000005，原因 unknown；正常退出、工具错误及 guard 拒绝均不作为 SIQ 验收通过。 |
| OpenClaw WSL2 | 5 项预检通过；4 次 agent 尝试均未完成工具调用 | 最新 A04 在独立 namespace 中通过私有 `/tmp` 和降权检查，CLI 仍 exit 1、23.756 秒、无超时；0 provider 请求或连接，目标前后不存在。 |
| WorkBuddy Windows | 本批未运行 | 仍缺已确认的独立测试用户或环境，未操作日常账号或桌面配置。 |
| 路径与 ACL 缺陷 | #42/#43 已补充最小方案并完成远端读回 | 尚未实现。共享调用点需按协作规则确认单一主修。 |

OpenClaw 的独立 namespace 探针仅证明临时目录隔离方案可行。A04 保留 `cli_error` 的 API 访问受限错误，但没有启用文件错误观察器，因此本轮致命 API 的来源仍 unknown，不能沿用 diag03 的 `/tmp` 定位。实际 network 日志有 1 条守卫初始化事件，不能写成“零网络事件”；已确认的是 provider 实际连接和请求均为零。自有进程、线程、socket 已收尾，父 namespace 和原 `/tmp` 元数据未变，安装源码摘要前后一致。A 未成功，B 未运行。

详细证据见 [共享核心组](shared-core/report.md)、[Hermes 组](hermes/report.md)、[OpenClaw 组](openclaw/report.md)。Issue [#42 的交接](https://github.com/maoyadongsh/siq-agent-security/issues/42#issuecomment-5659217797) 指出不能只加入 DACL 拒读而保留 Token 的读错后递归路径；[#43 的交接](https://github.com/maoyadongsh/siq-agent-security/issues/43#issuecomment-5659217300) 指出状态目录尾空格会在 product.Env 中提前被删除，须在归一化前检查原始状态根输入。静态新增发现与旧实测分别表述，不把设计当补丁通过。

[ACL 修复设计](designs/issue42-windows-private-read-design.md) 与 [状态路径设计](designs/issue43-windows-state-path-design.md) 包含入口、拟议行为和原生正负向计划；均未实现或复验。本批不为等待共享归属修改生产代码。Windows Hermes wrapper 测试适配另在独立分支准备，后续新候选的通过结果不能覆盖本批原失败。

共享核心测试固定源码 `9cc18630be584692905e1ce612b91a9ba5aee610`，运行前后干净。PR #45 已合并，但未把测试改标为合并提交实测。Hermes 诊断时 SIQ 检出固定为 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`；旧 SIQ 实现候选 `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` 及 Windows 二进制仅作身份核对，没有在宿主启动诊断中执行或加载 SIQ 插件。

整理时已抓取 main `b303c6f92392f3a44c306d81ad7323c6291ef4f2`，包含 PR #46 的 v4 任务书，并从该提交另建 `codex/windows-host-evidence-20260914` 纯证据分支；测试中没有 pull 或替换固定源码。PR #44 的既有 NTFS/ACL 证据保留在其原分支。本批不混合原 18×8 平台合同与 N09 v2 的 9×J1–J11 旅程矩阵，也没有新增原生通过项。原矩阵和既有 #39/#42/#43 缺口不变。

各子包保留冻结时的原字节。子报告中的“未提交”“交付准备”等语句描述子包组装时点，外层报告及 Git 历史负责记录后续归档和提交状态，不能为了更新展示时间而破坏子清单摘要。

本批公开材料仅含脱敏派生、合成数据、测试脚本及摘要；完整私有原件、状态、凭据、个人路径与调用原文不归档。Python audit guard、Node API guard 和 Windows Job 各有明确范围，不宣称它们构成完整 OS 沙箱。全部实际超时、非零退出和收尾限制保留。没有真实付费模型调用、日常配置更改、主线写入或发布动作。

归档校验首次 `git diff --check` 返回 2，原因仅为七个冻结 JSON 的 CRLF 行尾。逐行确认没有尾随空格或制表符后，按仓库既有做法在本目录 `.gitattributes` 对这七个文件声明 `whitespace=cr-at-eol`；其他空白检查仍启用，原字节及全部子清单 SHA256 不变。
