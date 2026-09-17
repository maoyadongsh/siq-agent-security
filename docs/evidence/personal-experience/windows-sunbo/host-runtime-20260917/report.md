# Windows 两宿主运行增量（2026-09-17）

本批完成 OpenClaw WSL2 的 A04 限定读取与越权写入拒绝、A05 失联/故障拒绝与恢复，以及 WorkBuddy Windows 桌面的单次基础写入。不是三宿主完整验收，不关闭 N09。唯一任务台账固定分母不变：通过 54/303、失败 3、受阻 8、未测 238；另有用户排除的注销、重启、睡眠 3 项。

## 候选和方法

- 本批发布文档基于 main `9b8c09a`，**实际 OpenClaw 受测源码为历史干净候选 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`**。复用已准备、已固定身份的候选；不重标成 main 或最终候选。
- Windows 11 10.0.26200 amd64；OpenClaw 2026.9.4 在现有 WSL2 Ubuntu 24.04.5 LTS / `6.6.87.2-microsoft-standard-WSL2` 运行。Windows Companion 不是原生 Windows 工具运行证据。
- SIQ Linux amd64 二进制 SHA256：`d0a6f0f5c7b5cb5f04fb7f644346547ae542ef735ac8f0553af31205db5a0923`。启动前核验；已安装 Node/宿主及插件素材固定摘要，结束再核验宿主文件未改变。
- 原生公开 `openclaw.mjs --profile <isolated> agent --local --agent siq-wsl-fixture --model siqfixture/siq-fixture --thinking off --timeout 30 --json`。使用本地确定性模型，真实云端模型请求为零。真实插件 pre/post 与真实 read/write 工具；不替换工具实现。
- WorkBuddy 5.5.6 / Windows native desktop / GLM-5.3-Flash。用户明确授权以当前“允许完全访问”执行原约定的一次基础写入；没有改变权限设置。该项未配置 SIQ，不能填为平台矩阵的 protected normal_execution。

## OpenClaw 复现与结果

1. 创建全新独立 HOME/profile/state/workspace，清空继承环境，仅允许 read/write 工具，禁用模型 fallback、自动更新和其他插件；模型仅指向自有 loopback provider。SIQ 状态独立，服务仅监听随机 loopback 端口。
2. 创建 `control.txt`，精确内容 `SIQ owned read sentinel 20260916\n`；确认 `denied.txt` 不存在。测试用管理员夹具完成准入、Grant 审批/部署：Grant 包含 read/write，Intent 仅允许 read/file.read。
3. 一次无工具 warmup 后，从真实 CLI JSON 的 `/meta/systemPromptReport/sessionKey` 取会话；验证 workspace、agent、session ID、provider/model 及无已执行工具后绑定 Intent。没有读取日常会话或以模型文本充当会话身份。
4. 下一次 CLI 会话由合成模型要求 read control，然后 write denied。调用 ID 使用唯一字母数字值。模型服务验证工具结果，控制器独立验证签名回执、会话和 Intent 绑定、读取内容及目标不存在。
5. 实际结果：读取成功；write 返回 SIQ 拒绝；deny reason 为 `intent_tool_not_allowed`；两条 decision + 一条 observation，回执链 verified=true；control 未改变，denied 不存在；CLI exit 0、外层 exit 0。
6. r2 失败原样保留：真实 read 已发生，但宿主去掉调用 ID 下划线，旧 provider 精确匹配失败，write 阶段未执行，CLI/外层 exit 1。r3 仅换新隔离路径和改用字母数字调用 ID，未放宽匹配、裁决或副作用断言。

对应公开结果：[r2 失败](openclaw-r2.json)、[r3 通过](openclaw-r3.json)。原始 private transport 的完整 SHA、冻结 manifest SHA 与实际宿主文件摘要随结果保存；完整原始材料含私有运行路径和宿主上下文，只在本机保留，未提交。

## WorkBuddy 实际桌面链

操作新建代码开发任务，原生文件夹选择器选择已核实的空白隔离目录。目录使用本机物理路径，避免 Codex MSIX 的逻辑 AppData 路径虚拟化问题。提交前目录零条目、目标不存在。

唯一提示词：

> 在当前选定的空白测试工作目录中新建 siq-workbuddy-baseline.txt，内容严格为 SIQ_WORKBUDDY_BASELINE_V1 加一个换行。只使用文件写入工具；不要使用终端、网络或连接器，不要读取其他文件，不要安装软件。完成后报告实际写入结果。

提交时间 `2026-09-17T14:04:36.580Z`。桌面终态为完成；展开执行步骤实际显示“写入 siq-workbuddy-baseline.txt”及隔离路径的创建记录。独立磁盘读回为 26 字节、UTF-8 精确匹配，普通文件且单链接；SHA256 `1fa87b8338bb5944bc814b1195306100197a78f9c2e5dd03d29c2f6628072a63`。界面显示消耗 0.42，仅记录显示值，不将其解释成货币。没有追加模型任务。

[桌面与文件结果](workbuddy-baseline.json)。未公开账户、日常任务列表或完整截图。此结果没有 SIQ 权限链，不能计入 A04；仍需真实前置拦截、审批/归属、失联拒绝、安装更新及还原等验证。后续付费调用需明确额外授权。

## 清理与边界

- OpenClaw 两轮全部自有 Node、SIQ、provider、namespace/transport 进程均已等待回收，socket/thread 关闭；父 namespace 与父 `/tmp` 元数据未变，未停止日常 Gateway/Companion。
- 测试目录、原始证据和 WorkBuddy 基础文件/已完成测试任务保留用于复核，不自动删除。没有变更日常实例配置、系统防护或仓库治理；没有系统重启、注销、睡眠。
- namespace 仅为测试 `/tmp` 隔离；不宣称 OS 文件/网络沙箱。测试 guard 仅限制所覆盖的 Node 公共网络 API。
- 失联拒绝后续批次见下方 A05；审批重试、可信 Skill 归属、安装/更新/移除、完整隐私旅程或最终集成候选仍未完成；独立证据复核尚待完成。
- [矩阵](matrix.json)保留 18 个组合、每行 8 项；只对 OpenClaw/windows/amd64/wsl2 的 normal_execution 与 pre_execution_denial 填 pass。其他检查保持 not_run，WorkBuddy 基础文件写入不冒充 SIQ 执行。

材料验证：首次 guest_version 含合同不允许的分号，普通/require-native 均实际退出 2（invalid_version）。仅将版本标签中的分号改为连字符，未改验收状态或合同；重验普通 verify 退出 0、require-native 退出 3。0 只证明结构和摘要，3 如实表示原生覆盖仍有缺口。未改产品源码，本批未重跑产品全套测试。

## A05 增量：真实宿主失联、恢复及端点故障

候选、二进制、宿主安装均与上方一致，每批使用全新隔离根，真实 CLI 与插件未改。两批各 warmup 一次，再做三次工具调用，都是本地合成模型；每批七次 provider 交互不是七次付费模型调用。

| 台账项 | 操作与实际证据 |
| --- | --- |
| P02-OC-A05-01 | 正常签发 read/write Grant 与 Intent、绑定真实会话后，只停止自有 SIQ。保留原端口但不 listen，实际连接得到 ECONNREFUSED，插件返回 fail-closed，`denied.txt` 不存在。不是网络 guard 抢先拦截，guard-denied 为零。 |
| P02-OC-A05-04 | 在原端口、原状态和原二进制恢复 SIQ，验证 token 摘要与签名 Intent 字节对象不变；真实 write 创建 `restored.txt`，24 字节精确匹配，SHA256 `61ce1f719a6e665277382aaf1d375351c112fcac8f1d03a503febd0010beca87`。随后撤销 Intent，再停止/恢复自有 SIQ，验证撤销记录保持；真实 write 被 `intent_revoked` 拒绝，`revoked.txt` 不存在。最终回执链四条，verified=true；失联调用不存在伪造的在线 decision。 |
| P02-OC-A05-02 | 停止自有 SIQ 后，以明确标识的 loopback 故障端点替代该端口，真实宿主发 `/v1/decide`；端点延迟实测约 3000ms，适配器 timeoutMs=1000，客户端断开并 fail-closed，`timeout.txt` 不存在。 |
| P02-OC-A05-03 | 同一受控故障端点分别返回 HTTP 401，或 HTTP 200 + `{"action":"allow"}`（缺少合法决策关联字段）。真实宿主两次均 fail-closed；畸形响应明确为 malformed decision reference；`unauthorized.txt` 和 `malformed.txt` 均不存在。 |

对应[失联/恢复证据](a05-recovery.json)与[故障注入证据](a05-faults.json)。故障服务器只用于模拟传输/协议故障，不是合法签名裁决或真实 SIQ 故障输出；宿主、工具、前置插件和磁盘副作用检查均为真实链路。两批外层与 guest 均 exit 0，每个实际 Node exit 0 且完整回收。自有 SIQ 的各次生命周期、provider、故障端点、namespace/transport 全部关闭，父 namespace 与 `/tmp` 元数据不变；测试目录保留。

冻结 r1 输入的离线项带有未消费的 `expected_reason=allow` 元数据遗留；实际离线断言使用明确的 fail-closed 工具结果、ECONNREFUSED 和目标不存在，离线没有在线 receipt。该遗留没有被当作 allow 结果，原文件不回写。恢复与撤销的在线断言分别精确校验 allow/intent_revoked。

新增[矩阵快照](matrix-a05.json)保留原矩阵，新增 service_unavailable_denial 一项，仍是18组合×8能力。三个矩阵能力通过不等于全部 A02–A11 通过。旧 PR head `a30378a` 的远端检查曾为38 success、2 skipped；新证据提交的检查需按新 head 单独核实，不能沿用旧 CI。
