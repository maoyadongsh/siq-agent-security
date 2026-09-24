# 企业环境首次接入验收（E143）

日期：2026-09-23。接续 E142，落实 ENT-UX-01 的首次接入核心流程。用户已授权直接修复过程中发现的问题；外部安全复核 SEC-F01–SEC-F10 保持后续顺序，总目标继续 active。

## 用户可见变化

企业“环境与设备”由列表扩展为创建环境、注册设备、核对心跳、提交发现任务和查看候选的接入流程。创建只填写名称和类型，采用现有 discovery 模式；同名返回明确冲突提示，保留输入并引导继续已有环境。环境 ID 保留在 URL，刷新可重新读取进度，不重新签发注册码。

用户填写目标设备可访问的控制面根地址，选择 Bash 或 PowerShell，按页面命令接入。注册码只在组件内存显示，可显式复制，不写 URL、Web Storage 或命令文本；Edge 新增标准输入注册码参数，并拒绝覆盖已存在的设备状态。旧参数保留兼容。页面不提供尚未验收的二进制下载或自动部署按钮。

状态分别表示已注册等待心跳、最近心跳正常、心跳超时、设备停用，以及扫描排队、已上传、已完成、失败、过期。任务提交前重新读取心跳；没有在线且声明支持所选采集器的设备时不提交。心跳是带查询时间的事实快照，不宣称持续在线。扫描范围明确列出，Hermes 和 OpenClaw 分别显式提交，不自动扩大扫描。

发现回执展示本次对象数、证据数及本环境证据总数，未知计数不补零。发现不自动纳管，也不表示运行时权限生效；组织资产入口明确是组织清单。设备/任务标识放在折叠详情中。进度读取失败撤下旧成功状态，用户可显式刷新恢复。

## 实际缺陷与修复

原生 Edge 首次验收能够完成 Hermes 扫描，但上传失败。`UploadBatch` 把包含 `[]*Candidate`、`[]*Evidence` 的 Go map 直接交给只支持 JSON 值的规范化器，产生 `canon: unsupported type []*protocol.Candidate`，随后真实任务回执为失败。

现先序列化成实际 wire JSON，再用保留数值字面量的解析器转为 JSON 值并规范化签名。签名算法、线协议和全局 CanonicalJSON 语义不变。新增真实 HTTP 捕获批次验签、修改 task_id 后拒绝的测试；两种原生 Connector 的批次又分别通过 Python 控制面真实验签及回执读回。没有把按钮请求成功当作扫描成功。

新建两个版本化只读合同：`environment-onboarding-access/v1` 与 `environment-onboarding/v1`。后者先按验证身份定位租户内环境，再检查权限；设备最多 100 条，扫描最多 20 条，明确截断。只返回所需摘要，不返回注册码、设备凭据/公钥、扫描路径或配置原文。读取不修改到期任务或写入审计。创建同名错误映射复用数据库现有唯一约束，冲突回滚审计与 outbox。没有数据库结构变更。

## 验证结果

| 验证 | 实际结果 |
| --- | --- |
| Hermes 企业浏览器 | 15 项通过；真实 API 创建、注册码复制、原生 Edge 注册/心跳、Hermes Connector 扫描、签名上传、回执、候选名称独立读回 |
| OpenClaw 企业浏览器 | 同一 Edge 候选、独立隔离环境下 15 项通过；实际 OpenClaw Connector 扫描及上传；两组共有检查不当作 30 个不同场景 |
| 按钮与恢复 | 创建、复制、终端切换、提交扫描、刷新进度、刷新恢复、组织资产链接实际可用；重复注册保留原状态、同名 409 不增环境；注入 503 撤下旧状态并恢复 |
| 界面 | 桌面及 375px 接入/结果截图已检查；接入区域无横向溢出。未声明完整键盘、200% 缩放或全部企业页面验收 |
| API | 全量 976 项通过；含权限拒绝、跨租户 404、吊销/超时投影、证据隔离、分页截断、无密钥输出、GET 不写入、同名事务回滚与 Schema 校验 |
| 数据库迁移 | 临时 SQLite 干净库按 Alembic 0001→0016 回放通过；不是本轮 PostgreSQL 生产迁移验收 |
| Edge | Go 测试、race、vet 通过；Linux amd64/arm64、macOS arm64、Windows amd64 构建通过 |
| Connector | Hermes 与 OpenClaw 各自模块测试通过；Linux aarch64 真实二进制用于上述浏览器旅程 |
| 前端 | 44 文件 / 267 项通过；企业与本地构建、TypeScript 检查通过；开发身份的隔离 UI 单独构建用于浏览器测试 |
| 个人端回归 | 新嵌入 UI 候选通过 E142 结果/证据浏览器 32 项；本地 Go 44 个测试包、vet 与四目标构建通过 |
| 静态检查 | API app Ruff、新浏览器脚本 Ruff、git diff --check 通过 |

候选 Edge：`var/flagship/ux-e143/edge-agent-final`，SHA-256 `d801fa0d9689aef5428e262db54563e139cadda13143907664801a099a20f320`。

最终浏览器证据为 `browser-hermes`、`browser-openclaw`、`local-results`。源文件、合同、二进制、构建资源与验证日志的摘要见 [E143 证据](../evidence/flagship-optimization-20260921/ux-enterprise-onboarding-e143.json)。保留前端大包构建提示及 Starlette/httpx 弃用提示，未为消除提示擅自升级依赖。

## 验收边界与剩余任务

两条企业旅程使用真实控制 API、原生 Edge 和 Connector，但身份为隔离开发身份，数据库为临时 SQLite，框架配置为合成 fixture；不读取真实用户凭据、不调用模型，不代表生产 IAM 或原生模型执行业务验收。PowerShell 命令切换和 Windows 构建通过，不代表 Windows 原生注册/运行已经验收。真实 DGX Spark 主服务、已安装版本及 Hermes 0.21 基线未替换。

ENT-UX-01 保持部分完成：可信安装分发、更少终端步骤、生产 IAM/真实设备部署、首次使用耗时测量、失败原因与修复动作、更多设备管理仍待接续。企业角色工作台、审批旅程、业务结果产物与最终发行仍在总任务中。Edge 设备吊销管理、重定向等外部检查条目没有借本轮假记完成。

历史失败保留：早期原生上传揭示上述真实缺陷；新增 Go 测试一度把字符串属性写成错误类型，修正夹具后全量通过；浏览器原先在已纳管视图立即断言新候选可见，改为点击“发现候选”、等待真实数据并核对 API 中的名称，未放宽产品行为。之后补齐复制和终端按钮检查，最终两框架使用同一脚本版本通过。

## 复验与回滚

仓库根执行，输出目录必须不存在：

```bash
python3 scripts/enterprise-experience/onboarding-browser-smoke.py \
  --framework hermes \
  --edge var/flagship/ux-e143/edge-agent-final \
  --connector-dir var/flagship/ux-e143 \
  --web var/flagship/ux-e143/dev-web \
  --out-dir var/flagship/ux-e143/recheck-hermes
# 改 --framework openclaw，并使用新的输出目录，可复验 OpenClaw。
```

隔离浏览器 UI 构建显式启用 VITE_DEV_MODE，仅用于测试；生产部署使用正常企业构建和生产身份配置。回滚限于本批前端、只读投影与 Edge 增量并重建产物，保留既有设备状态、审计、授权和原脏工作树。未提交、推送、发布或更新已安装应用。
