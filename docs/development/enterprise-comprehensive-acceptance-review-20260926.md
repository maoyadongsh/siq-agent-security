# 企业主线综合验收、修复与剩余门槛

日期：2026-09-26。对象：`deepseek/enterprise-mainline-closeout-20260926` 的当前工作树，
基线 HEAD `2dd8b1f496a2d891263c2b3421d58d09a1a54b50`。

## 1. 结论与范围

本轮在[首轮风险检查](deepseek-enterprise-mainline-review-20260926.md)基础上，
扩大到后端全量、前端全量与正式构建、全部 Go 模块 race/vet、30 条企业浏览器旅程、
真实隔离 PostgreSQL 迁移/并发、合同导航与提交导入闭包。
发现的问题已按先负例复现、再最小修复处理，没有删测试、放宽授权或增加业务功能。

**工作树的工程验证已显著补齐，但企业主线仍未完整交付验收通过。**
全量测试覆盖现有实现，不证明任务书中尚未接线的需求已经完成；未逐行复核全部并行作者成果，
未完成真实 IAM、OpenShell 防御效果、双架构原生安装或签名发行验收。
工作树未冻结，测试对象不是可独立重建的已提交候选，不给出主观完成百分比。

用户本轮单独授权一次性隔离 PostgreSQL：只使用本机已有镜像、回环地址、不挂载宿主目录、
不连接现有数据库。已按该边界执行，结束后容器销毁，另查容器列表无本次容器残留。
该许可不包含真实网关策略写入、沙箱 upload/exec、部署、推送或签发。

## 2. 已复现并修复的问题

### 2.1 JWT 私有权限声明类型混淆

旧 `_identity_from_claims` 迭代 `permissions` / `role_codes`，并用 `str()` 归一。
`permissions: "*"`、`permissions: {"*": false}` 或 `role_codes: {"admin": false}`
可被当成合法权限集合；tenant/sub 等异常类型也可被归一为身份。
这是**受信签发方签出的异常声明被错误解释**，不是绕过签名验证。

修复：tenant/sub 必须非空字符串，type 必须合法字符串；角色与权限必须为字符串数组，
不接受字符串、对象、null 或混合类型冒充。缺省数组仍为空，合法 admin/wildcard 语义不变。
九项类型负例先失败后通过；另外加入三项真实 RS256 验签到 HTTP 端点的拒绝回归，
使用合成密钥/JWKS，不读取真实凭据。

文件：`apps/control-api/app/security.py`、`app/tests/test_identity_jwt.py`、
`app/tests/test_oidc_jwt_verify.py`（后两路径相对 control-api）。

### 2.2 前端合同枚举被数组/对象冒充

`String(value)` 与对象键强制转换，让 `['effective']` 等非字符串通过某些枚举检查。
涉及控制台身份、部署预览、变更评审、批次/预约状态及角色技能来源投影。
修复为先检查原值 `typeof === 'string'` 再做精确成员判断，不改合法合同、权限或 API。

两组负例分别得到修复前 **4 failed / 20 passed** 与 **3 failed / 76 passed**。
部分同模式字段原本会在后续检查被拒，保留为回归护栏，不将其冒称新漏洞。

修改模块及对应测试均在 `apps/web/src/api/`：

- `consoleContext`、`deploymentPreview`、`changeReview`、`deploymentBatch`。
- `deploymentSubmission`、`roleSkillSelections`、`roleSkillSources`、`roleSkillSnapshotComparison`。

### 2.3 行为证据允许集合没有绑定独立读回

即使目标、revision、digest 已核对，调用方仍可自述一组虚构 `allow_rule_pairs`，
再提供与自述一致的允许臂，旧逻辑可能升级为 `enforcement_verified`。
新增负例修复前 **1 failed / 62 deselected**。

在 `cli_backend.py` 将已通过结构验证的允许集合与独立解析的策略读回集合精确比较，
不一致保留读回等级，原因固定为 `probe_binding_allow_set_mismatch`。
`test_enforcement_probe.py` 增加回归，直接相关两文件 **95 passed**。

本修复仍**不证明**失败来自策略阻断，也不证明报告的脚本路径就是实际被治理的二进制身份。
真实因果对照与执行身份的不足仍是生产行为等级验收阻断，未运行真实行为探针。

### 2.4 浏览器夹具过时，五条既有失败归因并修复

首次重跑已知五脚本为 **0 passed / 5 failed**。修复集中于：

- 手动接入移入折叠区后，脚本须先展开；明确选择目标设备，不依赖隐式设备选择。
- 模拟浏览器身份与脚本 HTTP 核验身份一致，使用合成最小所需角色，不跳过产品权限检查。
- 主导航标签更新为四领域，越权不可见与直达拒绝断言继续保留。
- 部署丢响应注入定位到实际持久预约端点 `/deployment-submissions`，保留旧预览失效夹具；
  按真实只读恢复语义检查提示、入口与状态，仍断言只发生一次写请求，不自动重发。

涉及 `scripts/enterprise-experience/` 下的 `candidate-review`、`onboarding`、`workspace`、
`change-execution`、`deployment-preview` 五个 `-browser-smoke.py`。
中间曾因本次临时连接器命名错误而失败，纠正为 `*-connector` 后重跑；这是验收配置错误，
不记为产品缺陷。没有把改变断言当作修复业务权限。

### 2.5 375px 资产页按钮裁切——截图发现、补负例再修复

初次 30 条旅程全绿后，实际查看截图发现资产页顶部三个操作横向被裁切。
页面 `overflow` 会隐藏溢出，仅检查 document.scrollWidth 不足以证明按钮可见。
补充逐按钮 bounding rect 必须落在 viewport 的断言，旧构建实际失败
`mobile header action is clipped`。

修复 `AgentsPage.tsx`：去掉 actions 内额外 nowrap 容器，使用 React fragment，
让既有 PageHeader 的 flex-wrap 生效。不改共享 CSS、配色、字体或业务操作。
修复后再次实际查看 375px 截图，三按钮完整显示、描述正常换行。
遵循 React skill，仅做必要结构调整，没有性能重构或 UI 重设计。

### 2.6 合同审计工具敏感路径与符号链接边界

原扫描可能读取 `var/`、`backups/`、临时目录内 JSON、`.env.*.json` 或链接目标，
将运行数据当合同字面量；合成临时仓库的两项负例先得到 **2 failed / 12 deselected**。
未用真实秘密复现。

修复扫描排除目录、`.env` 族、符号链接路径和非普通文件；别名目标也检查链接边界。
不宣称这些路径检查解决了恶意并发文件替换的全部 TOCTOU 问题。
文件：`contract-version-chain-audit.py` 及其测试。

随后现场扫描发现 `local-admin-session/v1` 建档告警：实际合同明确位于
`packages/contracts/local-client-session.v1.schema.json` 的 `definitions.session`。
逐字段核对后在 `contract-version-aliases.json` 登记异名映射，没有新造合同或忽略告警。
最终未建档版本 **0**、坏导航 **0**、有文档但未检出生产字面量 **89**。
最后一项是静态工具观察，不自动等于 89 个缺失功能，也不等于完成全部 wire 合同验收。

### 2.7 编译/静态清理

后端完整 Ruff 原报六处导入顺序/未使用导入；只修 `app/main.py`、
`migrations/env.py`、`0002_finding_resource_ref.py`、`0003_asset_evidence_ids.py`、
`0004_classification_run.py` 的导入，不改迁移操作。真实 PG 升降级验证通过。
后端 Ruff 使用 control-api 配置；根目录脚本使用根目录默认规则。
曾误在 control-api 目录对外部脚本套用后端严格配置，报 130 项主要为旧长行风格，
没有为消除这类跨目录误用进行批量格式化；分别从所属目录复查通过。

## 3. 本轮实际验证与证据边界

证据根目录：`/tmp/siq-deep-review-myY7ar/`。这是临时本机证据，不是发行制品，
不保证跨机器/重启后永久留存；重验须重新生成，不复用历史绿灯。

| 检查 | 实际结果 | 证明范围 |
| --- | --- | --- |
| 后端全量 `pytest -o addopts='' -q app/tests` | 2250 passed / 1 skipped | 当前工作树合成数据库/适配器测试；既有 skip 保留 |
| 前端 `npm test` | 112 文件 / 1012 passed | 产品逻辑/解析/交互测试，不是浏览器或真实身份 |
| 正式模式标准构建 | `VITE_DEV_MODE=false`，tsc + vite 成功 | 独立 `/tmp/.../web-production-reviewed`，未覆盖 dist、未部署 |
| Go 全模块 | 14 个模块 race + vet 通过 | `edge/agent`、全部 `connectors/*`、`apps/agentshield`，Linux ARM64；不是其它平台原生验收 |
| 发行/来源/门禁/探针工具选定回归 | 126 passed / 14 subtests passed | 合成输入、替身命令，不执行签发或正式候选发布 |
| 合同扫描与门禁回归 | 55 passed | 与上一行部分重叠，不累加为独立用例数 |
| 真实隔离 PostgreSQL | 18 项 checks 为 true | 迁移保护、预约/调度并发和事务；OpenShell 适配器仍为替身 |
| 30 条企业浏览器旅程 | **30 passed / 0 failed / 0 blocked**，含移动修复后复跑 | 模拟身份构建；其中 8 条自起回环 dev API，其余 route mock，不是生产 IAM |
| 合同版本导航 | 0 未建档 / 0 坏链接 | 静态词汇与链接，不证明运行期所有合同 |
| HEAD 导入闭包 | **未通过**，grafted_count=39 | 当前 HEAD 需补入 39 个工作树文件才能形成工具检查的后端导入闭包 |

后端结果保存 `backend-final.xml`，前端 `web-final.log`，正式构建 `build-final.log`；
PG `postgres/result.json`，源码导入 `import-closure/report.json`，
合同 `contract-version-final.json`。Go 与部分定向测试结果在本轮执行输出中，未冒称另有永久日志。
Starlette/httpx 既有弃用警告仍存在，不通过安装依赖来消除。

浏览器初始全绿 `browser-all/result.json` 之后还有移动负例与修复；以最终目录为准。
已实际查看的截图包括资产桌面/375px、导航桌面、部署移动弹窗和接入结果。
未逐张审阅全部套件生成的每一幅截图。

主要复核命令（从仓库根执行，使用已安装环境）：

```bash
cd apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests
uv run --no-sync ruff check app migrations
cd ../web
npm test
VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-review-fresh-production-output
```

```bash
# 下列 --out 等输出必须换为未使用路径；不可用模拟身份构建发布。
python3 scripts/enterprise-experience/run-browser-smoke-suite.py \
  --repo . --out /tmp/siq-review-fresh-browser-output \
  --edge /tmp/siq-deep-review-myY7ar/edge-agent \
  --connector-dir /tmp/siq-deep-review-myY7ar/connectors
python3 scripts/enterprise-experience/contract-version-chain-audit.py \
  --repo . --out /tmp/siq-review-fresh-contract.json \
  --aliases scripts/enterprise-experience/contract-version-aliases.json
python3 scripts/enterprise-experience/import-closure-check.py \
  --repo . --ref HEAD --out /tmp/siq-review-fresh-import-output
```

## 4. 对照主线的剩余工作，不用测试数量替代需求完成

| 单元 | 本轮结论 | 剩余动作 |
| --- | --- | --- |
| R00 / R08 来源与发行 | 未收口 | 逐路径核对作者归属、导入/构建闭包，取得准确提交与冻结范围；本轮不替并行作者提交 |
| R01 安装/持续发现 | 后端、调度、CLI 已有大量隔离验证；普通安装衔接未完成 | 补枚举到 CLI 独立确认的接线；真实身份/systemd/升级恢复另验 |
| R02 角色与技能 | 配置声明、安装观察的现有代码通过验证 | 不把这些投影当实际运行加载；精确版本/加载关系缺权威证据时保持未知 |
| R03 拓扑 | 内部只读投影不是完整运行拓扑 | 权威设备/容器/沙箱来源与获准采集旅程仍需接通并验收 |
| R04 绑定与影响 | 重读/并发拒绝已有测试；共享影响前置未全满足 | 确认独占/共享标准、版本失效与证据边界；不能因内部 readiness 存在就开放业务确认 |
| R05 批量治理与恢复 | 单项恢复浏览器故障已排除 | 依 R04 补批量执行用户闭环、独立回滚复核，保留未知不重发 |
| R06 审计 | 查询/关联/导出与证据降级现有实现通过回归 | 完整引用闭环及保留/删除治理仍需明确政策；不擅自实施删除 |
| R07 集成门禁 | 本轮大范围重跑并修复 | 来源冻结后对同一候选集中复验；不能给脏工作树盖正式发行章 |
| R09 真实交付 | PostgreSQL 门槛本轮补齐一部分 | 真实 IAM、OpenShell 因果行为及双架构原生安装、受控签发、发布部署仍未验 |

建议收口顺序：先确定当前源码集合/归属；只推进 R01 可明确接线和已有授权范围内的
R05/R06 缺口；涉及业务标准的 R04 先作明确决策；最后对冻结候选跑一次统一门禁。
不再不断派生文档/扫描子任务来代替上述产品缺口，也不重复已经完成的边界修复。

## 5. 交付状态

本记录形成时，修复均留在现有工作树并保留其他作者改动；用户随后另行授权统一提交与合并，
具体提交及合并状态以 Git 历史为准。该授权不包含推送、签发或部署，本验收结论本身也不构成发行批准。
未读取 IDE 打开的密码、真实 `.env`、私钥或设备种子；未扫描真实用户配置，
未修改现有数据库/网关策略，未降低防攻击能力或把 unknown 改为受保护。

这是一轮有广泛实际验证的综合复核，不是“全项目无漏洞”或“所有任务完成”的声明。
本记录与首轮记录互补，不能用本轮通过项覆盖历史失败、未达成需求或外部验收门槛。
