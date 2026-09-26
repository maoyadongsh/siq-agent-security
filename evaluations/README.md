# 测评与验收结果

[机器索引](catalog.json) · [外部复现](external/README.md) · [提交要求](templates/README.md) · [当前缺口](gaps.md) · [研究](../research/README.md) · [平台](../platforms/README.md)

本目录登记“谁以什么候选，在什么环境、协议下观察到什么”。执行器留在 benchmarks/scripts，测试留在所属模块，原证据留在历史路径。索引引用不增加实测次数，代码合并、源码 CI、制品验签、原生安装、真实宿主与桌面人工验证不能互换。

| 记录 | 已归档结果 | 范围 |
| --- | --- | --- |
| 0.3.1 正式发行（新增记录） | 官方验签/本机启动通过，3/3 篡改拒绝，8/8 回读 | `f3d9c3f`；[独立发行记录](../docs/evidence/releases/0.3.1/README.md)，不计入下方原有 15 条 catalog，也不扩展平台验收 |
| 0.3.0 包检查 | 14/14 | `83fde2d`；官方根、内容/程序 pin、六条拒绝、Linux ARM64 bootstrap/控制台/停止与包内空状态启动步骤 |
| 0.3.0 远端回读 | 8/8 资产一致 | 与已验候选逐字节比较，实际公开下载与签名 URL 暂存；Latest 是回读时状态 |
| 0.3.0 源码 CI | 5/5 工作流成功 | 不是五项测试，不能与历史 31 项必需检查合并分母 |
| 0.3.0-rc.1 包检查 / 回读 | 13/13；8/8 | `58ab22e`；首次启动文档检查是后来正式包新增，不回填 RC |
| Linux 已装旅程 | B02 16/16，R07 31/31，嵌套 R04 31/31 | 第六代候选 `67bc48c4…`、测试发行根；不属于正式版全量旅程 |
| Linux OpenShell D05 | 365 pass / 7 partial / 1 blocked / 0 fail，共 373 步 | 同第六代候选；不是 373/373 全通过 |
| Linux UI 会话修复 | Web 117/117；真实浏览器定向 2/2 | 第八代局部候选 `a85c76b0…`；不继承第六代系统级验收 |
| V5 固定控制 | 23/23；正常 5/5；不安全目标实际执行 0/13 | 不同分母，不合成为总体拦截率；保留研究原始定义 |

## 原方案指定的补充对照

以下为同一机器目录补齐的七条记录，连同首批八条共 15 条；全部来自原档案，没有重跑或提升支持状态。

| 记录 / 精确候选见 catalog | 观察 | 必须保留的边界 |
| --- | --- | --- |
| 第六代 OpenShell B3 | 57/57 功能步骤 | 不含性能预算、桌面或后端远端单任务停止 |
| 第六代受控 OpenClaw 2026.9.4 | 22/22 公共 CLI 检查 | 固定补丁副本、合成模型/操作者；不是上游原版审批验收 |
| 第八代直接 R07 / 嵌套 R04 | 30/30；31/31 | `a85c76b0…`，直接复制程序与 headless 浏览器；不继承第六代 systemd/OpenShell |
| 企业 PostgreSQL + RS256/JWKS | 27/27 隔离配置检查 | apps/control-api 记录为 `2187fea`；loopback 测试签发者，非客户 IdP、HA 或生产运维 |
| Windows 控制端 / OpenClaw WSL Agent | 7 项最小检查 | `ff166068…`；合成模型；首轮 harness 失败保留；不是 Windows 原生 Agent 或批准恢复 |
| Windows Hermes 原生 CLI | 5 项记录案例 | `72140795…`；合成模型；无桌面、独立第二轮或吊销后重启验收 |
| Windows WorkBuddy 5.5.6 桌面 | 2 次原生任务记录，含安装 Skill 读写 | `6841a495…`；不是完整验收率；早期超时保留，审批恢复/桌面升级未验证 |

旧报告“待签”与取消前的任务状态保留原文，现行状态以[当前任务](../docs/development/current.md)、[主线整合](../docs/development/main-branch-integration-20260926.md)、[全面验收](../docs/development/enterprise-comprehensive-acceptance-review-20260926.md)及[平台页](../platforms/README.md)解释。当前主线 CI 通过仍不改变任何历史候选的原生验收或发行身份；一次记录被多处链接不增加独立重复次数。

各行精确证据路径、SHA-256、候选与未记录字段见 catalog。源提交、证据提交、集成提交和实际程序摘要是不同身份；dirty 候选不得补造 clean SHA。历史 Windows 原生/WSL 与 macOS 协作者记录见[平台页](../platforms/README.md)，其他未纳入机器索引的结果继续留在原台账，目录不声称穷尽全部测试。

新增索引先补证据和范围，再由 `python3 scripts/repository/check.py --base origin/main` 验证；原报告失败、重跑和 partial/blocked 保留。公开材料不可带运行密钥、token、配对码、私有模型配置或客户原文。


## 后续源码基础检查

[四目标源码检查](../docs/evidence/repository-reorganization-final-20260919/README.md)另外登记 Linux amd64/arm64、macOS arm64、Windows amd64 的自建程序、准入与基础启动链路，及缺发行清单时拒绝 bootstrap 的边界。这批记录不在上表 15 条历史 catalog 中，不改写其分母，也不扩展 0.3.0 正式包的原生验收。查某项功能时，应同时核对[模块说明](../apps/README.md)、[宿主适配](../adapters/runtime/README.md)与该次候选报告。
