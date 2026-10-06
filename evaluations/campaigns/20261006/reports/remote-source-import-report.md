# 真实公网来源导入、摘要保护与兼容性测评

日期：2026-10-06。作者侧真实产品实测；不是独立第三方认证。

本轮补齐了公网HTTPS导入成功与错误摘要拒绝的真实对照。`remote-source-import-003`完成8次管理HTTP请求，71/71项冻结检查通过；固定归档导入201、重复请求200复用，错误摘要409拒绝且未发布候选。SIQ将公开Skill的出网要求记录为`declared`能力，并未自动授予权限或安装。前两批失败完整保留。

## 实际入口与实验条件

使用既有固定候选产品二进制，SHA256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。真实初始化、启动daemon、配对管理凭据，通过`POST /v1/skill-imports/remote`进入生产HTTPS下载与归档验证路径。没有替换下载器、注入私有拨号器、关闭TLS验证或放宽公网地址检查。

001使用宿主默认网络。系统与产品解析均得到198.18测试网段，产品拒绝URL；这一环境下不能证明摘要或内容校验。002/003使用本批隔离Docker桥接网络，以冻结DNS转发器将原始查询经验证证书的HTTPS DNS提交，原样返回回答。产品仍自行解析、检查地址、建立TLS并下载；该条件只代表隔离网络环境，不代表宿主默认网络已修复。容器、镜像及清理记录独立保存。

独立预检下载公开原始ZIP并冻结字节摘要；测评后对比产品签名的归档/文件树及实际落盘。归档没有重打包。第三方内容只供扫描导入，未进入安装或业务执行步骤；不将其脚本当作测评指令。

## 三批结果与真实原因

| 批次 | 公网来源与环境 | 实际结果 | 解释 |
|---|---|---|---|
| 001 | 默认网络；仓库commit `063bee…` | 28/56检查，7次远端请求全部400 `skill_import_url_blocked` | 环境解析到测试网段，未达到内容/摘要对照 |
| 002 | 隔离HTTPS DNS；相同公开归档 | 32/56检查；错误摘要409，其余远端400 `skill_import_invalid` | 已建立公网连接并下载；整包根目录CLAUDE.md为符号链接，合法子目录也不能绕过整包检查 |
| 003 | 同隔离环境；无符号链接的真实历史commit `09b1ed…` | 71/71检查，8次请求均符合冻结预期 | 兼容归档的正向路径与拒绝路径均有证据 |

这些检查数不是独立攻击样本或防护率，分母也不能横比：成功记录会触发额外签名、文件与身份检查。前两批仍为`all_passed=false`；完整性验证成功仅表示失败记录可复核。

003取自[公开固定版本](https://github.com/vercel-labs/agent-skills/tree/09b1edecbe21da26ffdce94cd670700170fac034)。原始ZIP为13057字节，SHA256 `adfd24e2b3e1ef899163b246e38efcb5f43c26871aee1536985ca2f3e977c5f7`。选择`skills/vercel-deploy`，包含SKILL.md和scripts/deploy.sh共9989字节、一个scripts目录；脚本可执行位参与记录比对。完整ZIP共10条目、展开21390字节。选择历史版本是为了获得符合当前导入合同的真实控制，不消除新版本整包被拒绝的兼容性事实。

## 003逐项控制

| 请求 | 预期及实际 | 证据重点 |
|---|---|---|
| 本地正常ZIP控制 | 201 | daemon/管理认证和基本导入可用 |
| 公网归档＋正确摘要＋有效子目录 | 201 | 原始归档摘要/字节、文件树、可执行位、目录与签名匹配 |
| 原请求原ID重试 | 200 | `reused=true`且记录完全相同 |
| 同归档、错误预期摘要、新ID | 409 `skill_import_archive_mismatch` | 错误位于摘要层，候选状态没有变化 |
| 同归档、不存在的子目录 | 400 `skill_import_invalid` | 无发布 |
| 同归档、根目录不含SKILL.md | 400 `skill_import_invalid` | 无发布 |
| 已有ID取消预期摘要要求 | 409 `skill_import_conflict` | 不能以修改请求覆盖原来源身份 |
| 新ID、不指定预期摘要 | 201 | 内容身份相同，来源定位身份不同；实际归档摘要仍记录 |

真实准入结论为`admit_with_conditions`：脚本中的外部HTTPS端点被识别为能力声明，状态为`declared`，类别为`capability_declaration`。这与“检测到出网就隔离”不同，符合产品将能力审阅和恶意隔离区分的设计。导入来源的TrustLevel/摘要也不能提升为发布者身份认证。

6份唯一签名文档（3个导入记录及对应准入）验证成功；两处受控逃逸目标的独立文件事件与前后状态未见效果，校准正常；没有Grant或安装文件。daemon的已建立公网443 TCP连接采样与DNS回答中的`140.82.116.10`、`172.182.252.132`相符。采样窗口覆盖管理请求，PID归属匹配。它不是逐请求TLS抓包，也不是所有文件/网络副作用不存在的证明。

## 证据、复核与失败保存

- 原始可导出证据：[001](../data/remote-source-import-001/manifest.json)、[002](../data/remote-source-import-002/manifest.json)、[003](../data/remote-source-import-003/manifest.json)。每批7文件白名单导出；私有凭据、状态目录、daemon日志及第三方原始ZIP未导出。
- 冻结验证：[001](remote-source-import-001-verification.json)、[002](remote-source-import-002-verification.json)、[003](remote-source-import-003-verification.json)。003锚点为`82c33f686dd70525782a76fd328f4869ecf263116b75d90ed528d418f18a4cab`；其他锚点在inventory/anchors中。
- [补充交叉复核](remote-source-import-003-review.json)核对独立下载的原始ZIP文件树、签名树摘要、原始文件事件、观察窗口以及DNS/公网连接；12种篡改证据均被拒绝。这是事后加强复核，不修改原始评分。
- [容器环境及清理](remote-source-import-003-container-environment.json)、[DNS及执行日志](remote-source-import-003-container-logs.json)、[导出检查](remote-source-import-003-export-review.json)。两容器及本批网络移除、捕获的宿主进程身份均已退出。
- 补充复核器首次独立打包漏带辅助模块，发生ModuleNotFoundError；[原错误](remote-source-import-review-001-error.json)保留。新review-002自包含辅助函数后成功，未重跑业务或改变原数据。
- [测评框架回归](remote-source-import-framework-tests.txt)与[工程验证记录](remote-source-import-engineering-validation.json)。

## 对方案的修订及边界

来源导入必须同时验证网络可达、整包安全、所选Skill存在、归档身份、准入事实和后续授权；仅有“拦截”文案无法判断命中了哪一层。公网正向控制应在冻结前检查完整ZIP类型/预算，同时保留不兼容公开仓库作为实际限制。网络环境变更和来源变更必须另建批次。

SRC09补齐隔离网络中的公网生产下载；SRC10补齐正确/错误预期摘要真实对照；SRC11覆盖有效子目录、缺失子目录及无根SKILL选择。来源路径逃逸、完整预算边界、重定向/混合DNS/证书/分块超限真实公网矩阵、可控上游变化及中断仍需继续。生产Git导入门禁保持关闭。

这批没有新原生宿主运行、真实模型调用或独立任务块；不能推导自然提示注入防护率。已有[本地ZIP→批准安装→原生工具](native-zip-onboarding-report.md)保留原范围，不能与本批拼接为同一公开来源的完整安装运行旅程。企业同候选闭环、其他OS、确认集和独立第三方复核仍未完成。
