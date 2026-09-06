# SIQ Agent Security：Kimi 审查仲裁与统一评估补充

- 时间：2026-09-06 02:27:35 +08:00（Asia/Shanghai）。
- 基线：`0723f88cf4a242be6bf3f679996f5795ef75028e`；本轮静态核对时工作区干净。
- 原工程审查：[engineering-review.md](/home/maoyd/reviews/siq-agent-security-2026-09-06/engineering-review.md)。
- 外部输入：[用户提供的 Kimi 报告](/home/maoyd/.codex/attachments/4a8b1399-fa08-4f72-b472-ee95eb3954ee/pasted-text.txt)。
- 执行规划：[带时间戳的开发计划](development-plan-20260906-022735.md)。本文与原工程审查共同构成统一评估，保留原报告的证据与限制。

## 1. 仲裁结论

**需要统一纳入，但不直接拼接、不照单接受严重度，也不把 Kimi 自述的实测当成本次独立验证。** 历史签名材料、本地凭据暴露、发布信任根、JWKS 更新、扫描资源边界、证据脱敏等是重要补充。原审查的丢写、跨语言签名、任务恢复、UI 治理断点和错误显示仍需保留，不因新报告侧重安全而降低其开发优先级。

将原文复合条目拆成 **50 个可追踪主张**；S2a/S2b、H5a–c、M-P5a–f 等后缀是本轮定位编号，不是 Kimi 自带漏洞 ID。逐项结论为 **9 项 confirmed、39 项 needs_review、2 项 not_actionable**。这不是“50 个漏洞”或 CVSS 评分：

- `confirmed`：在注明的受支持前提下，静态证据可连接具体输入、控制缺口与后果；不代表发生过生产攻击。
- `needs_review`：原始安全主张仍有前提、边界或完整攻击链缺口。其中不少工程缺陷已经确定并被采纳；“待安全复核”不等于“不修”。
- `not_actionable`：当前证据不支持该条原始漏洞主张；可以保留相关文档或防御建议，但不为它虚增已确认漏洞数。
- confirmed 与 needs_review 分别独立排序，队列内从 1 连续编号。该顺序衡量可利用性与未决风险；DEV 任务的优先级另含数据正确性、交付依赖和产品价值。

## 2. 必须修正的建议

| 议题 | 统一判断 |
| --- | --- |
| 历史控制面签名密钥 | 本地历史路径可达已核对；在役设备是否仍信任未知。把历史密钥视为暴露材料，优先核对信任指纹并撤销旧信任。删除提交、清理历史都不能撤销已复制密钥；不能把任务签名钥自动等同于发布钥。 |
| “真人批准” | HTTP 自报 human 或 TTY 检测不能证明人类身份；伪终端、同 UID 读文件/进程的能力必须考虑。配对可修复无认证 bootstrap，但强 Agent 隔离还需独立身份和凭据不可达。 |
| DNS rebinding | Host/Origin 缺口纳入 P0 修复与验证；完整浏览器远程链保留待验证状态。Chrome 的本地网络访问许可机制已变化，实际结论须记录浏览器版本、许可状态与网络条件。 |
| Skill 内容哈希 | Python bootstrap 漏检值得修；Go CLI 已有 HashSkillDir 比较，不能重复实现或宣称全链都未校验。 |
| 发布信任 | “自己提供公钥并验自己签名”只能证明自洽，不能证明可信发行者；同包根需要真实分发信任起点。复制文件后执行也不能单独消除同 UID 篡改/TOCTOU。 |
| 检测 | Python 已有部分 AST；保留 Go 能力差异。引号、目录名、代码围栏都不是安全语义的可靠充分条件。能力声明不得一律升级 quarantine。 |
| JWKS | 缺 TTL 成立；优先用已有依赖或明确时钟缓存实现，不为简单 TTL 直接引入新依赖。旧 token 的 exp 校验仍然存在。 |
| 回执完整性 | 现存链前缀有效与历史完整是两件事；同目录签名 checkpoint 仍可整体回滚。外部锚点是可选增强，离线产品要诚实展示证明范围。 |
| Edge 重放 | 有效签名、任务 TTL、回执终态检查确实存在；应设计逻辑任务幂等、结果重传与租约恢复，不能一刀切拒绝重复投递。 |
| 凭据哈希 | 高熵随机设备 secret 使用 SHA256 不等同于弱口令哈希问题；没有证据要求以 Argon2/pepper 重做凭据体系。 |
| 构建锁 | 镜像应强制锁文件一致性；仅 `--frozen` 不校验 lock 是否与项目声明同步。选择 `--locked` 或等价的受控导出安装链。 |
| 测试缺口 | CodeBuddy 已有 fail-closed 表测试；需要补的是完整异常矩阵、OpenClaw TS 及真实安装/卸载旅程。 |
| 生产部署 | 开发 Compose、可信 dispatch 输入和可变 Action 标签属于特定边界下的风险；不能直接写成公网可利用漏洞。 |

密钥撤销优先于历史清理的依据见 [GitHub 泄漏密钥处置说明](https://docs.github.com/en/code-security/tutorials/remediate-leaked-secrets/remediating-a-leaked-secret)。高影响操作绑定独立审批的方向见 [OWASP AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html#high-impact-action-integrity-controls)。浏览器条件需随实测版本记录，参见 [Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access)。以上是修复设计参考，不是对本项目攻击已成功的证明。

## 3. 方法和证据限制

本轮使用 `codex-security:triage-finding` 对用户提供的主张进行逐项静态仲裁；没有新建子代理、运行应用、编译、测试或攻击 PoC。原工程审查的临时环境实验证据明确标为“原审查已复现”，不升级为本轮动态复测。

逐个影响路径解析了安全策略，未发现适用的 SECURITY.md；因此使用根/本地 AGENTS.md、安全不变量、ADR-011、本地开发规格和现有 threat-model.md 作为次级边界依据。历史删除路径以 apps/control-api 为最近现存范围；路径已不存在、私钥未读取、当前信任未知均保留为缺口。没有适用 SECURITY.md 不意味着任意表面都属于受支持的强安全边界。

本轮未调查真实生产身份、设备信任、DNS/浏览器攻击链、特殊文件动态行为、全部 Connector 越界链、当前依赖 CVE 和网络隔离能力。原 Codex Security 深扫因托管只读 worker 权限前提不满足而未启动，该缺口仍存在。本文不是完整深扫结果、漏洞清零证明或生产安全认证。

## 4. 逐项结果

每项都保留独立来源与判定，不在仲裁层去重；合并只发生在开发任务层。所有条目共同存在“缺适用 SECURITY.md、未进行本轮动态验证”的证据限制。路径/行号对应以上基线，实施前须按符号重新定位。

### S1｜历史控制面任务签名种子泄漏

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 1 位。部分接受；P0 核查；对应 [DEV01](development-plan-20260906-022735.md#dev01)。
- 输入及前提：历史仓库读取者；当前设备仍信任历史密钥。声称后果：旧任务签名密钥可能用于伪造受信任务。
- 证据位置：历史删除路径 `apps/control-api/signing-key.seed`（提交 364dade / 145e53f）。本地 Git 历史在 364dade 引入、145e53f 删除该路径，现有分支历史仍可到达；CI 注释也记录了该历史对象。
- 反证、范围或待补证明：未读取私钥内容；未证明当前生产签名身份或任何在役 Edge 仍信任对应公钥，也未证明已经发生伪造任务。
- 下一步：按 DEV01 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### S2a｜ui-config 无认证返回管理 token 与自报真人批准

- 结论：`confirmed`；置信度 high；队列 confirmed 第 1 位。接受；P0；对应 [DEV02](development-plan-20260906-022735.md#dev02)。
- 输入及前提：本机可连接监听端口的进程；本地 daemon 正在监听；调用者无需状态目录读取权限。声称后果：读取管理 token 并访问管理操作。
- 证据位置：[apps/agentshield/internal/server/server.go:93-129,165-180,507-533](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/server/server.go:93)。/ui-config.json 未经过 auth，返回同一管理 token；loopback 来源限制没有区分 OS 用户；此 token 可进入配置及 grant 管理入口，actor_type 被入口写成 human。
- 反证、范围或待补证明：loopback 限制确实存在；这里确认本机无认证获取管理凭据与管理调用链，不据此声称浏览器远程链已验证；同 UID 的强隔离另受产品边界限制。
- 下一步：按 DEV02 开展范围明确的修复与负向验证；当前仅交付计划。

### S2b｜无 Host 校验导致浏览器 DNS rebinding 攻击链

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 2 位。部分接受；P0 验证；对应 [DEV02](development-plan-20260906-022735.md#dev02)。
- 输入及前提：诱导访问恶意站点的远程攻击者；浏览器实际允许相关本地网络访问且解析链可控。声称后果：经 DNS rebinding 读取 loopback 管理凭据。
- 证据位置：[apps/agentshield/internal/server/server.go:106-114](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/server/server.go:106)。Handler 检查 RemoteAddr，但没有 Host/Origin 白名单；与无认证 ui-config 构成值得优先验证的链。
- 反证、范围或待补证明：浏览器版本、本地网络许可、DNS 缓存及访问条件尚未验证，不能直接确认任意远程网页可成功完成攻击。
- 下一步：按 DEV02 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H1｜bootstrap 默认允许未钉二进制与 adapter 脚本不验签

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 3 位。部分接受；P1；对应 [DEV04](development-plan-20260906-022735.md#dev04)。
- 输入及前提：被替换的分发包或本地二进制搜索路径；攻击者能改变被信任的搜索结果或发布输入。声称后果：执行未绑定发布摘要的二进制。
- 证据位置：[skills/siq-agent-security/scripts/bootstrap.sh:52-64](/home/maoyd/siq/siq-agent-security/skills/siq-agent-security/scripts/bootstrap.sh:52)。发布入口在未要求 pinned 时默认传 --allow-local；adapter.sh 独立搜索二进制后执行，未复用同一次校验结果。
- 反证、范围或待补证明：本地源码构建兼容是显式开发用途；PATH/env 受可信操作者控制时不是自动成立的提权漏洞。需区分发布默认与开发覆盖。
- 下一步：按 DEV04 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H2｜同包信任根与 Skill content_hash 未校验

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 4 位。部分接受；P1；对应 [DEV04](development-plan-20260906-022735.md#dev04)。
- 输入及前提：被篡改的 Skill 分发内容；攻击者可影响包内容；分发信任锚未被独立认证。声称后果：内容替换未在 bootstrap 完整性验证中被发现。
- 证据位置：[skills/siq-agent-security/scripts/verify_manifest.py](/home/maoyd/siq/siq-agent-security/skills/siq-agent-security/scripts/verify_manifest.py)。Python bootstrap 验证器校验签名与二进制，但没有覆盖 Skill content_hash；验证器、公钥、内容共包需要明确外部信任起点。
- 反证、范围或待补证明：Go CLI release.go:125-139 已调用 Verify 并比较 HashSkillDir 与 content_hash。不能说所有入口都不校验，也不能把同包公钥本身等同于漏洞。
- 下一步：按 DEV04 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H3｜Go manifest-verify 使用清单自带信任根

- 结论：`confirmed`；置信度 high；队列 confirmed 第 2 位。接受；P1 发布阻断；对应 [DEV04](development-plan-20260906-022735.md#dev04)。
- 输入及前提：不可信发布清单提供者；使用当前 Go manifest-verify 校验第三方清单。声称后果：自签清单被报告为发布验证通过。
- 证据位置：[apps/agentshield/internal/skillmanifest/manifest.go:196-218](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/skillmanifest/manifest.go:196)。Verify 优先使用输入清单 SignedBy，只有为空才回退 ReleasePublicKey；manifest-verify 直接用此函数作发布验证。
- 反证、范围或待补证明：Go 的内容哈希校验仍存在，但攻击者可同时声明内容哈希并用自己的密钥签名；Python 验证器有外部公钥匹配检查。此结论限 Go 发布验签入口。
- 下一步：按 DEV04 开展范围明确的修复与负向验证；当前仅交付计划。

### H4｜重装覆盖备份与非原子配置修改

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 16 位。接受工程缺陷；P1；对应 [DEV07](development-plan-20260906-022735.md#dev07)。
- 输入及前提：用户既有配置及重复安装请求；执行重复安装或遇到无效配置。声称后果：安装卸载破坏配置完整性。
- 证据位置：[apps/agentshield/internal/adapterinstall/install.go](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/adapterinstall/install.go)。固定备份在重复安装时被覆盖；原工程审查 R08 的隔离实验已证明重装后卸载留存 hook、坏 JSON 被覆盖。
- 反证、范围或待补证明：已证明配置恢复缺陷；进一步的低权限恶意文件利用及非原子写入崩溃攻击未在本轮完成。
- 下一步：按 DEV07 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H5a｜多行检测绕过 Go/Python

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 8 位。部分接受；P1 验证；对应 [DEV06](development-plan-20260906-022735.md#dev06)。
- 输入及前提：恶意 Skill 脚本作者；样本绕过所有适用检查且按规格应判为威胁。声称后果：多行威胁未被预期检测。
- 证据位置：[apps/agentshield/internal/threat/threat.go:178-192](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/threat/threat.go:178)。Go 正则以单行执行，存在跨行语义识别缺口。
- 反证、范围或待补证明：Python threat_analysis.py:208-252,319 已有 AST 路径覆盖部分多行 subprocess(shell=True)；不能确认报告所称两边一概绕过；具体样本需逐类复核。
- 下一步：按 DEV06 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H5b｜docs/assets 等区域降级超出规格

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 6 位。部分接受；P1 验证；对应 [DEV06](development-plan-20260906-022735.md#dev06)。
- 输入及前提：Skill 包作者；构造实际可达恶意内容且其余检查未拦截。声称后果：有执行语义内容被文档区启发式降级。
- 证据位置：[apps/agentshield/internal/admission/dispositions.go:40-46,68](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/dispositions.go:40)。references/evals/assets/docs 及 SKILL.md 以外 .md 进入 docs 区，正则命中在此被降级为 info。
- 反证、范围或待补证明：独立的凭据外传、欺骗等检查仍可能命中；不能推导这些目录里的任何恶意代码必然通过。目录名不足以证明内容只作示例。
- 下一步：按 DEV06 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H5c｜引号启发式降级提示注入

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 7 位。部分接受；P1 验证；对应 [DEV06](development-plan-20260906-022735.md#dev06)。
- 输入及前提：Skill 提示文本作者；恶意指令满足启发式并绕过其他独立检查。声称后果：真实指令被示例启发式降级。
- 证据位置：[apps/agentshield/internal/admission/dispositions.go:146](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/dispositions.go:146)。isExampleLine 把引用前缀或两个引号视作示例，参与提示注入/欺骗命中的降级。
- 反证、范围或待补证明：还需按完整准入决策表验证最终 verdict；不能把任意加引号直接等同于完整门禁绕过。
- 下一步：按 DEV06 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### H6｜JWKS 永久缓存与虚假60sTTL

- 结论：`confirmed`；置信度 high；队列 confirmed 第 4 位。接受；P1；对应 [DEV08](development-plan-20260906-022735.md#dev08)。
- 输入及前提：持有仍满足 JWT 其他条件的旧签名材料者；IdP 在进程存活期间轮换/撤销 key；旧 key 已被缓存。声称后果：IdP 密钥移除不能按所述 TTL 传播至进程。
- 证据位置：[apps/control-api/app/security.py:96-127](/home/maoyd/siq/siq-agent-security/apps/control-api/app/security.py:96)。自定义 _fetch_jwks 使用无 TTL 的 lru_cache；当前进程对相同 URL 不再刷新，因此新 kid 不可见、移除的旧 key 仍留在信任集合。
- 反证、范围或待补证明：并非 PyJWKClient 自带缓存；JWT 自身 exp 仍校验，不能声称过期 token 也一直可用。实际 IdP 轮换时间未调查。
- 下一步：按 DEV08 开展范围明确的修复与负向验证；当前仅交付计划。

### M-D1｜Go manifest 未知字段与原文签名语义分叉

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 17 位。接受兼容性缺口；P1；对应 [DEV09](development-plan-20260906-022735.md#dev09)。
- 输入及前提：第三方/新版签名文档生产者；输入含消费者未知但签名涉及的字段。声称后果：生产者与消费者签名语义不一致。
- 证据位置：[apps/agentshield/internal/skillmanifest/manifest.go:254-263](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/skillmanifest/manifest.go:254)。Go json.Unmarshal 到类型结构会丢弃未知字段，而 Python 验证器以原始字典参与签名规范化。
- 反证、范围或待补证明：跨语言合同缺口成立；未知字段是否承担安全语义需按具体合同确定，不等于已经能伪造有效签名。
- 下一步：按 DEV09 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-D2｜Unicode 行切分及正则词边界分叉

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 18 位。接受差分验证任务；P1；对应 [DEV06](development-plan-20260906-022735.md#dev06)。
- 输入及前提：非 ASCII 或特殊换行的 Skill 内容作者；差异字符参与具体规则或位置判定。声称后果：两引擎检测与证据定位分叉。
- 证据位置：[apps/agentshield/internal/threat/threat.go:192](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/threat/threat.go:192)。Go 自定义 CR/LF 切分与 Python splitlines 范围不同；RE2 与 Python 的词边界语义需要公共语料锁定。
- 反证、范围或待补证明：不能由实现差异直接量化漏报；需保留源字节摘要与原行定位，不能简单全局替换后改写证据。
- 下一步：按 DEV06 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-D3｜两引擎 quarantine 判定不同

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 19 位。部分接受；先对齐规格；对应 [DEV06](development-plan-20260906-022735.md#dev06)。
- 输入及前提：同一内容的不同产品入口；该条 verdict 属于双方承诺对等的策略范围。声称后果：quarantine 策略不一致可能误导治理。
- 证据位置：[apps/agentshield/internal/admission/dispositions.go](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/dispositions.go)。本地 disposition 与控制面严重度映射并非同一个政策层。
- 反证、范围或待补证明：仓库明确区分能力声明与隔离理由；不接受把所有 curl/sudo 等能力统一 quarantine 的建议。共享检测要对等，政策差异要显式声明。
- 下一步：按 DEV06 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-D4｜规则包同版本接受与严格递增文档冲突

- 结论：`not_actionable`；置信度 high；不入可利用性队列。拒绝自动定为漏洞；文档需改；对应 [DEV04](development-plan-20260906-022735.md#dev04)。
- 输入及前提：拥有有效签名规则包的操作者；必须存在已承诺的严格递增边界，但当前证据不支持。声称后果：同版本安装被声称为防降级绕过。
- 证据位置：[apps/agentshield/internal/rulepack/rulepack.go:261](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/rulepack/rulepack.go:261)。实现按低于内置版本拒绝，同版本可接受；相关说明与严格递增表述不统一。
- 反证、范围或待补证明：接受同版本不自动构成降级，当前规格允许不低于内置版本；如要防历史回滚，需另立持久化最高已接受版本合同。
- 下一步：按 DEV04 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P1｜生产 issuer 未强制且 refresh 可充当 access

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 5 位。接受防御改进；P1 验证；对应 [DEV08](development-plan-20260906-022735.md#dev08)。
- 输入及前提：持有非预期 token 类型或 issuer 的调用者；token 满足其他校验且部署未施加额外 issuer/type 约束。声称后果：令牌用途混淆访问业务 API。
- 证据位置：[apps/control-api/app/security.py:75-127](/home/maoyd/siq/siq-agent-security/apps/control-api/app/security.py:75)。type=refresh 被映射为 user；生产配置仅强制 JWKS URL，oidc_issuer 可为空。
- 反证、范围或待补证明：实际 IdP refresh 的 aud/claims、issuer 部署值未核实；jwt.decode 仍校验签名、aud、exp 等，不能推导所有 refresh 都能访问。
- 下一步：按 DEV08 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P2｜多处事件审计 flush 前取 ID

- 结论：`confirmed`；置信度 high；队列 confirmed 第 9 位。接受并合并 R05；P1；对应 [DEV11](development-plan-20260906-022735.md#dev11)。
- 输入及前提：合法创建或自动状态变化请求；对象 ID 由 insert/flush 默认赋值，而载荷在此前构造。声称后果：审计/outbox 引用不能可靠指向状态对象。
- 证据位置：[apps/control-api/app/routers/environments.py](/home/maoyd/siq/siq-agent-security/apps/control-api/app/routers/environments.py)。创建 ORM 对象后、flush 前把默认生成的 ID 写入事件载荷；R05 已复现 environment/change-request 的 null ID，源码同类见 rules/drift/deployment_verify。
- 反证、范围或待补证明：本轮未逐路由动态复测；补充路径以源码证据计，不把两处实验自动扩展成全部已复现。
- 下一步：按 DEV11 开展范围明确的修复与负向验证；当前仅交付计划。

### M-P3｜Dockerfile pip install 绕过 uv.lock

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 27 位。接受发布加固；P1；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：镜像构建期间的软件分发输入；重建时依赖解析结果发生变化。声称后果：镜像使用偏离审核锁的依赖。
- 证据位置：[apps/control-api/Dockerfile](/home/maoyd/siq/siq-agent-security/apps/control-api/Dockerfile)。镜像 COPY pyproject.toml 后 pip install .，未使用仓库 uv.lock，部署依赖不能由该锁唯一确定。
- 反证、范围或待补证明：这是确定的可复现构建缺口，未证明发生供应链植入或具体已知漏洞。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P4｜break-glass 到期覆盖业务终态

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 20 位。接受业务缺陷；P1；对应 [DEV12](development-plan-20260906-022735.md#dev12)。
- 输入及前提：到期的 break-glass 记录；审批记录满足到期筛选。声称后果：定时复核覆盖既有业务状态。
- 证据位置：[apps/control-api/app/worker.py:157-194](/home/maoyd/siq/siq-agent-security/apps/control-api/app/worker.py:157)。逾期 break-glass 查询未排除 effective/rolled_back 等业务终态，随后写 status=post_review_due。
- 反证、范围或待补证明：这是业务状态覆盖；是否造成具体越权取决于下游状态解释。复核状态应与部署生命周期正交。
- 下一步：按 DEV12 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5a｜高熵Edge secret裸SHA256无pepper

- 结论：`not_actionable`；置信度 high；不入可利用性队列。不列为必要漏洞修复，作为可选纵深建议保留；对应 [DEV08](development-plan-20260906-022735.md#dev08)。
- 输入及前提：获得 secret_hash 的数据库读取者；当前 secret 为高熵随机。原文建议增加 HMAC/pepper，同时也明确注明高熵 token 可接受；并未提供可行的明文恢复路径。
- 证据位置：[apps/control-api/app/routers/environments.py:197](/home/maoyd/siq/siq-agent-security/apps/control-api/app/routers/environments.py:197)。设备 secret 使用 token_urlsafe(32) 的高熵随机材料，存 SHA256；注册码也为高熵随机。
- 反证、范围或待补证明：Kimi 自身已经限定“高熵 token 可接受”。因此本项作为可选加固处理，不表述为其声称已经能离线破解；无证据要求强制改 Argon2 或引入 pepper 密钥运维。
- 下一步：按 DEV08 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5b｜重复device_identity产生500

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 30 位。接受错误处理缺口；P2；对应 [DEV11](development-plan-20260906-022735.md#dev11)。
- 输入及前提：持有效注册码的设备；数据库命中唯一约束。声称后果：重复身份触发 500 而非受控冲突。
- 证据位置：[apps/control-api/app/routers/environments.py:175-219](/home/maoyd/siq/siq-agent-security/apps/control-api/app/routers/environments.py:175)。注册添加 Edge 后直接 commit，没有对重复 device_identity 的约束异常作协议映射。
- 反证、范围或待补证明：需要有效注册码；不是匿名直接注册/身份接管证据。应在真实 PostgreSQL 验证并发注册与回滚。
- 下一步：按 DEV11 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5c｜客户端request_id污染审计

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 32 位。部分接受；P2；对应 [DEV11](development-plan-20260906-022735.md#dev11)。
- 输入及前提：API 请求者；下游错误地把客户端字段当可信身份或未限制存储/输出。声称后果：污染关联字段或妨碍审计归因。
- 证据位置：[apps/control-api/app/main.py:68-71](/home/maoyd/siq/siq-agent-security/apps/control-api/app/main.py:68)。优先采用客户端 X-Request-ID，部分审计入口直接读取同一 header。
- 反证、范围或待补证明：客户端关联 ID 是常见设计，不能充当身份事实；是否可日志注入取决于序列化与下游。需限长字符校验及独立服务端审计 ID。
- 下一步：按 DEV11 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5d｜注册端点无限流

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 29 位。纳入部署验证；P2；对应 [DEV11](development-plan-20260906-022735.md#dev11)。
- 输入及前提：可达注册端点的网络客户端；部署入口缺少有效容量与速率控制。声称后果：资源耗尽或滥用注册接口。
- 证据位置：[apps/control-api/app/routers/environments.py:175](/home/maoyd/siq/siq-agent-security/apps/control-api/app/routers/environments.py:175)。注册应用路径未见请求速率限制。
- 反证、范围或待补证明：注册码高熵、一次性、过期并使用行锁；未检查生产代理/WAF 的限制。不能由未限流推导注册码可穷举。
- 下一步：按 DEV11 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5e｜nginx缺安全响应头

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 33 位。纳入部署加固；P2；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：浏览器可访问的部署入口；实际入口没有由上游补充相应控制。声称后果：缺少浏览器纵深防护。
- 证据位置：[apps/web/nginx.conf](/home/maoyd/siq/siq-agent-security/apps/web/nginx.conf)。仓库 nginx 模板缺少完整安全响应头策略。
- 反证、范围或待补证明：开发模板不是生产暴露证据；CSP、frame 防护和 HSTS 应按实际 HTTPS/嵌入需求设计，不能在所有 HTTP 本地入口照抄。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-P5f｜enrollment TTL配置未生效

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 31 位。接受配置缺陷；P2；对应 [DEV11](development-plan-20260906-022735.md#dev11)。
- 输入及前提：有效 enrollment 请求；运维设置非默认 TTL。声称后果：配置声明的有效期没有被执行。
- 证据位置：[apps/control-api/app/routers/environments.py:156](/home/maoyd/siq/siq-agent-security/apps/control-api/app/routers/environments.py:156)。注册码失效时间写死 900 秒，config.py:129 的 enrollment_ttl_seconds 没有在此使用。
- 反证、范围或待补证明：默认值相同，只有运维配置改变时出现差异；不声称默认注册码永不过期。
- 下一步：按 DEV11 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G1a｜无扩展名二进制触发panic

- 结论：`confirmed`；置信度 high；队列 confirmed 第 5 位。接受；P1；对应 [DEV05](development-plan-20260906-022735.md#dev05)。
- 输入及前提：不可信 Skill 文件作者；无点相对路径、二进制或超出可扫描范围、无可执行位。声称后果：准入扫描 panic 中断。
- 证据位置：[apps/agentshield/internal/admission/admission.go:204-221,281](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/admission.go:204)。isNativeExt 使用 p[strings.LastIndex(p,"."):]；相对路径完全无点时索引为 -1。不可扫描/二进制且非 executable 的输入可进入该分支并 panic。
- 反证、范围或待补证明：不是所有无扩展名文件都触发；可执行位分支会短路，路径目录中有点也会改变条件。本轮为静态确认。
- 下一步：按 DEV05 开展范围明确的修复与负向验证；当前仅交付计划。

### M-G1b｜FIFO设备文件阻塞扫描

- 结论：`confirmed`；置信度 high；队列 confirmed 第 6 位。接受；P1；对应 [DEV05](development-plan-20260906-022735.md#dev05)。
- 输入及前提：能够提供本地 Skill 文件树的作者；扫描目录包含可打开的特殊文件。声称后果：扫描无限等待或超预算读取。
- 证据位置：[apps/agentshield/internal/admission/walk.go:110-121](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/walk.go:110)。addFile 没有普通文件检查就 os.ReadFile；大小预算使用文件 Stat，对 size=0 的 FIFO/设备不能约束等待与读取。
- 反证、范围或待补证明：实际设备权限依 OS；本地 Skill 根中可创建的 FIFO 已足以构成支持边界内输入风险。不得在真实工作目录用阻塞 PoC 验证。
- 下一步：按 DEV05 开展范围明确的修复与负向验证；当前仅交付计划。

### M-G2｜回执删除尾部无法检测

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 24 位。部分接受；P2 架构；对应 [DEV15](development-plan-20260906-022735.md#dev15)。
- 输入及前提：可修改回执存储的本机主体；验证者没有独立可信的链尾/最高序号。声称后果：历史尾部截断不被前缀验签发现。
- 证据位置：[apps/agentshield/internal/receipt/chain.go](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/receipt/chain.go)。Verify 可以验证现存前缀，缺少独立保存的预期链尾时无法知道较新尾部被删。
- 反证、范围或待补证明：同 UID 状态目录篡改在现有残余边界内；签名链保证现存记录完整性不等于完整历史。把 checkpoint 也放同目录不能防整个目录回滚。
- 下一步：按 DEV15 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G3｜回执seq/head竞争与并发半行读取

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 15 位。部分接受并合并 R09；P1；对应 [DEV03](development-plan-20260906-022735.md#dev03)。
- 输入及前提：并发决策与状态查询；并发到达对应路径。声称后果：回执链状态竞争/不一致读取。
- 证据位置：[apps/agentshield/internal/receipt/chain.go](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/receipt/chain.go)。Append 更新 seq/head 与 Head 读取缺少一致同步；R09 已用 race overlay 复现数据竞争。Read 与 append 的一致视图也需设计。
- 反证、范围或待补证明：seq/head 竞争已证实，但并发半行读取的完整具体链尚未复现；不把所有读错都写成已发生的签名损坏。
- 下一步：按 DEV03 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G4a｜hold重复决议产生矛盾回执

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 14 位。接受状态机缺口；P1；对应 [DEV03](development-plan-20260906-022735.md#dev03)。
- 输入及前提：持管理能力的重复/并发决议请求；原始 hold 存在且被多次提交。声称后果：同一 hold 出现互相冲突的解决记录。
- 证据位置：[apps/agentshield/internal/server/server.go:271-301](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/server/server.go:271)。从历史链查原 hold，ResolveHold 生成固定原 ID+-res，没有已解决状态/修订号判断；重复同意/拒绝可形成矛盾决议。
- 反证、范围或待补证明：仍需管理权限；是否直接改变工具执行取决于适配器消费。应按一次性决议合同修复，不宣称匿名绕过。
- 下一步：按 DEV03 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G4b｜畸形JSON被忽略后仍执行grant动作

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 13 位。接受输入处理缺口；P1；对应 [DEV03](development-plan-20260906-022735.md#dev03)。
- 输入及前提：持有效管理凭据的请求者；错误返回时部分字段已赋值并满足下游检查。声称后果：输入校验失败后仍可能执行状态动作。
- 证据位置：[apps/agentshield/internal/server/server.go:507-533](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/server/server.go:507)。grantAction 用 _ = readJSON 忽略错误，随后读取可能部分解码的 actor_id/reason 并执行状态动作。
- 反证、范围或待补证明：完全无效且 actor_id 为空仍可能被业务层拒绝；具体部分赋值错误需用合成请求负测。不能声称任意畸形 JSON 均批准。
- 下一步：按 DEV03 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G5a｜终端ESC/CSI/OSC注入

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 23 位。纳入专项验证；P2；对应 [DEV15](development-plan-20260906-022735.md#dev15)。
- 输入及前提：含控制字符的 Skill 元数据作者；未经适当转义的内容实际被终端解释。声称后果：终端显示/链接操纵。
- 证据位置：[apps/agentshield/internal/admission/card.go:23](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/card.go:23)。Skill Card 用 fmt 直接插入不可信 frontmatter 文本；CLI 输出需追踪控制字符最终消费路径。
- 反证、范围或待补证明：JSON 编码会转义部分控制字符；并非每个 excerpt 都原样输出到终端，需证明 ESC/CSI/OSC 到真实终端显示的链。
- 下一步：按 DEV15 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G5b｜Skill Card进入模型的不可信内容

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 22 位。纳入边界加固；P2；对应 [DEV15](development-plan-20260906-022735.md#dev15)。
- 输入及前提：Skill 文本作者；实际模型消费卡片并可影响高影响动作。声称后果：模型把内容解释为高优先级指令。
- 证据位置：[apps/agentshield/internal/admission/card.go:23](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/admission/card.go:23)。卡片展示不可信 Skill 描述等字段，Agent 可能将卡片作为工具结果阅读。
- 反证、范围或待补证明：卡片含输入不等于模型必然执行注入；转义/分隔符也不是可证明防线。需要保留不可信来源并由独立裁决/审批限制影响。
- 下一步：按 DEV15 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G6a｜Engine.sessions无界增长

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 25 位。接受容量缺口；P2；对应 [DEV16](development-plan-20260906-022735.md#dev16)。
- 输入及前提：有决策访问权的多会话调用者；持续提供新 session ID。声称后果：进程状态持续增长。
- 证据位置：[apps/agentshield/internal/receipt/engine.go:428-433](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/receipt/engine.go:428)。session(id) 为新 ID 分配 map 项，没有容量上限或淘汰。
- 反证、范围或待补证明：入口有 bearer；尚无生产负载数据，未量化 DoS。会话污点不能因简单 LRU 淘汰变成干净状态。
- 下一步：按 DEV16 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G6b｜assets/export全量扫描读取

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 26 位。接受性能缺陷；P2；对应 [DEV16](development-plan-20260906-022735.md#dev16)。
- 输入及前提：有本地 UI/API 访问权的请求者；资产/回执数量大或并发刷新。声称后果：重复请求放大 IO/内存与响应延迟。
- 证据位置：[apps/agentshield/internal/server/ledger_http.go:13](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/server/ledger_http.go:13)。snapshot 路径做 inventory 和全量 receipts 投影；export 同类全量读取。原审查已指出被忽略的错误与读写耦合。
- 反证、范围或待补证明：没有本轮压测，不给虚构 p95；正常规模下不代表已造成不可用。
- 下一步：按 DEV16 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G7｜未知enforcement_mode导致适配器fail-open

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 12 位。接受配置正确性缺口；P1；对应 [DEV07](development-plan-20260906-022735.md#dev07)。
- 输入及前提：运行时配置输入者；配置未经过可信枚举校验。声称后果：拼写/非法模式导致预期 block 变宽松。
- 证据位置：[adapters/runtime/hermes-agentshield/__init__.py](/home/maoyd/siq/siq-agent-security/adapters/runtime/hermes-agentshield/__init__.py)。Python/TS 将配置字符串与 block 比较，非枚举值可能进入宽松异常处理；Go 侧有严格模式校验。
- 反证、范围或待补证明：模式由操作者配置，不是已证实低权限输入；应拒绝未知值，并保留 audit_only/warn 的已定义 allow 语义。
- 下一步：按 DEV07 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-G8｜export敏感路径未完全脱敏

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 21 位。部分接受；P1 隐私契约；对应 [DEV15](development-plan-20260906-022735.md#dev15)。
- 输入及前提：带敏感路径的本地事实；相关字段包含敏感路径且导出被分享/同步。声称后果：脱敏导出暴露超过合同允许的主机信息。
- 证据位置：[apps/agentshield/internal/export/export.go](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/export/export.go)。Build 把 ResourceValue/Reason 等复制到导出记录，路径隐私需逐字段确认，不能只靠密钥 regex。
- 反证、范围或待补证明：路径并非都需去除，否则权限事实不可用；应明确家庭目录等脱敏策略。变换后的对象不能冒充仍保有原签名。
- 下一步：按 DEV15 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-E1｜Connector per-op超时无效

- 结论：`confirmed`；置信度 high；队列 confirmed 第 8 位。接受；P1；对应 [DEV10](development-plan-20260906-022735.md#dev10)。
- 输入及前提：挂起或不遵守协议的 Connector 进程；父上下文无 deadline 且子进程未按环境参数停止。声称后果：阻塞 Edge 调度，突破声明的操作超时。
- 证据位置：[edge/agent/connector.go:145,198-220,260](/home/maoyd/siq/siq-agent-security/edge/agent/connector.go:145)。opts.Timeout 传入 connector 环境，但 call 没有建立自己的 deadline；主循环上下文通常只有进程信号取消。子进程不响应时父端无法保证 per-op 限时。
- 反证、范围或待补证明：Connector 可能自行实现超时，但不构成父进程独立限制；还需覆盖 stdin 写入、响应读取与子进程清理。
- 下一步：按 DEV10 开展范围明确的修复与负向验证；当前仅交付计划。

### M-E2｜scope根符号链接绕过

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 9 位。部分接受；P1 验证；对应 [DEV10](development-plan-20260906-022735.md#dev10)。
- 输入及前提：能改变待扫描根/链接的内容提供者；具体 Connector 实际跟随该链接且目标超出授权根。声称后果：扫描越过已批准 scope。
- 证据位置：[edge/agent/protocol/protocol.go:238-315](/home/maoyd/siq/siq-agent-security/edge/agent/protocol/protocol.go:238)。ValidateScopeSafety 主要检查词法根路径，countGlobMatches 使用会跟随符号链接的 Stat。
- 反证、范围或待补证明：不能推导所有 Connector 会递归 symlink 根：directory 的 WalkDir 对根链接行为构成反证。必须沿每个 Connector 到读取点验证。
- 下一步：按 DEV10 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-E3｜systemd参数空格flag密钥脱敏缺口

- 结论：`confirmed`；置信度 high；队列 confirmed 第 3 位。接受；P1；对应 [DEV10](development-plan-20260906-022735.md#dev10)。
- 输入及前提：受扫描服务的含凭据启动参数；ExecStart 中敏感值采用当前 redactor 未覆盖的空格参数形式。声称后果：秘密明文进入可上传证据。
- 证据位置：[connectors/systemd/systemd.go:422-446](/home/maoyd/siq/siq-agent-security/connectors/systemd/systemd.go:422)。ExecStart 经 RedactString 后作为 exec_summary 进入 candidate 与 evidence；redactor 的键值模式不涵盖任意 '--password VALUE' 等空格形式，未匹配的值会留在输出。
- 反证、范围或待补证明：不是每个凭据都漏，已有固定前缀与 key=value 脱敏。这里确认任意不带已知前缀的敏感参数仍可入批次；未对真实主机采集或外传。
- 下一步：按 DEV10 开展范围明确的修复与负向验证；当前仅交付计划。

### M-E4｜directory walk无界攒文件

- 结论：`confirmed`；置信度 high；队列 confirmed 第 7 位。接受；P1；对应 [DEV05](development-plan-20260906-022735.md#dev05)。
- 输入及前提：可提供大文件树的扫描对象作者；扫描树含大量候选项。声称后果：在读取预算之前耗尽遍历资源。
- 证据位置：[connectors/directory/directory.go:218-278](/home/maoyd/siq/siq-agent-security/connectors/directory/directory.go:218)。遍历时持续 append foundFiles，并在全量收集后排序；文件数/字节/耗时判断主要在后续处理环节。
- 反证、范围或待补证明：没有负载实验与具体内存耗尽规模；但在不可信目录枚举阶段未落实有界扫描的控制链明确。
- 下一步：按 DEV05 开展范围明确的修复与负向验证；当前仅交付计划。

### M-E5｜Edge任务无过期强制与去重无限重放

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 11 位。部分接受；P1 恢复设计；对应 [DEV10](development-plan-20260906-022735.md#dev10)。
- 输入及前提：可重投合法签名任务的主体；存在无期限有效任务或重复投递绕过当前任务/回执约束。声称后果：重复执行副作用或长期有效任务。
- 证据位置：[edge/agent/task.go:82](/home/maoyd/siq/siq-agent-security/edge/agent/task.go:82)。Expired 对缺 expires_at 返回 false，Edge 侧未见完整持久化执行去重账本。
- 反证、范围或待补证明：控制面正常任务会签名并设置 TTL；回执端有重复/终态约束。任务至少一次投递本来需要重试，不能直接定为无条件无限重放或一刀切拒绝重试。
- 下一步：按 DEV10 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-E6｜openclaw配置读取缺symlink检查

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 10 位。部分接受；P1 验证；对应 [DEV10](development-plan-20260906-022735.md#dev10)。
- 输入及前提：能替换受扫描 openclaw.json 的主体；链接指向可读且可解析的外部配置。声称后果：读取授权根外的配置数据。
- 证据位置：[connectors/openclaw/openclaw.go:214-222,371](/home/maoyd/siq/siq-agent-security/connectors/openclaw/openclaw.go:214)。openclaw.json 读取经 os.Open，没有就近拒绝符号链接。
- 反证、范围或待补证明：输出只提取有限字段与摘要，不是任意文件原文上传；需要用合法 JSON 外部目标验证实际 scope 越界。
- 下一步：按 DEV10 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-C1a｜Actions未钉SHA及Pages权限范围

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 34 位。接受加固；P2；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：上游 Action 或可改工作流的主体；上游引用改变/被替换或权限被滥用。声称后果：构建执行偏离已审核内容。
- 证据位置：[.github/workflows/ci.yml](/home/maoyd/siq/siq-agent-security/.github/workflows/ci.yml)。Actions 使用可变版本标签；Pages job 的写权限应按实际部署步骤最小化。
- 反证、范围或待补证明：工作流/仓库写者是可信主体；mutable ref 风险不等于发生供应链入侵，Pages 发布需要部分写权限，不能一律撤掉。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-C1b｜OpenShell下载无哈希且workflow输入直接插值

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 28 位。部分接受；P1；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：受信工作流操作者或被替换下载源；可控制下载响应或具有 dispatch 输入权限。声称后果：执行未核验二进制/非预期 shell 内容。
- 证据位置：[.github/workflows/openshell-compat.yml:50-61](/home/maoyd/siq/siq-agent-security/.github/workflows/openshell-compat.yml:50)。下载 OpenShell CLI 缺摘要校验，workflow_dispatch 输入直接插值到 shell。
- 反证、范围或待补证明：dispatch 操作权限通常已受仓库控制；尚未证明低权限攻击者可控该输入。应经 env 传参、校验 URL/版本/摘要并限定运行权限。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-C2｜Mermaid动态CDN无SRI

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 35 位。接受静态站加固；P2；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：第三方脚本分发源；CDN 或依赖版本内容改变。声称后果：静态页面执行变化的外部脚本。
- 证据位置：[site/architecture.html](/home/maoyd/siq/siq-agent-security/site/architecture.html)。架构页面动态加载 CDN Mermaid，缺完整性固定。
- 反证、范围或待补证明：需结合站点敏感能力评估；未证明静态站脚本能接触控制面凭据。自托管固定资源比为动态 import 生硬添加 SRI 更可行。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-C3a｜未配置govulncheck

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 36 位。接受发布门禁；P2；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：已知漏洞依赖的供应链输入；实际存在受影响可达依赖；本轮未审计 CVE。声称后果：已知 Go 可达漏洞未被发布门禁发现。
- 证据位置：[.github/workflows/ci.yml](/home/maoyd/siq/siq-agent-security/.github/workflows/ci.yml)。当前 CI 未见 govulncheck。
- 反证、范围或待补证明：缺扫描工具不是存在具体可利用 CVE 的证据；工具版本、数据库新鲜度、不可用状态都需留存。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-C3b｜job无timeout-minutes

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 37 位。接受运行加固；P2；对应 [DEV17](development-plan-20260906-022735.md#dev17)。
- 输入及前提：挂起的构建/测试/下载步骤；步骤不能及时完成。声称后果：浪费 runner 时间或拖延交付。
- 证据位置：[.github/workflows/ci.yml](/home/maoyd/siq/siq-agent-security/.github/workflows/ci.yml)。工作流未配置明确 job timeout-minutes。
- 反证、范围或待补证明：平台本身有默认上限；缺更短项目预算不等于无限运行。
- 下一步：按 DEV17 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-T1｜威胁模型缺本地产品威胁

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 38 位。接受文档缺口；P1；对应 [DEV18](development-plan-20260906-022735.md#dev18)。
- 输入及前提：未明确建模的本地攻击者/输入；相关产品能力被以强边界交付。声称后果：安全承诺与实际防御边界不一致。
- 证据位置：[docs/threat-model.md](/home/maoyd/siq/siq-agent-security/docs/threat-model.md)。现有威胁模型侧重控制面/Edge，未完整表达本地 UI token、同 UID Agent、Skill 包来源、回执回滚等边界。
- 反证、范围或待补证明：本地 ADR、规格已有部分边界描述；不能说整个仓库完全没有本地威胁模型。文档缺口本身不是一个可利用漏洞。
- 下一步：按 DEV18 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

### M-T2｜OpenClaw CodeBuddy缺fail-closed负向测试

- 结论：`needs_review`；置信度 medium；队列 needs_review 第 39 位。部分接受；纠正 CodeBuddy 断言；对应 [DEV07](development-plan-20260906-022735.md#dev07)。
- 输入及前提：适配器收到异常响应/不可达服务；CodeBuddy 已存在对应测试，直接反驳全称结论。声称后果：声称缺少两平台失败关闭测试。
- 证据位置：[apps/agentshield/internal/adapters/adapters_test.go:84-106](/home/maoyd/siq/siq-agent-security/apps/agentshield/internal/adapters/adapters_test.go:84)。TestCodeBuddyHookFailClosedTable 已覆盖服务不可达、畸形输入、未知动作；Hermes 也有对应测试。
- 反证、范围或待补证明：原文同时断言 OpenClaw/CodeBuddy 缺 fail-closed 测试不准确；OpenClaw TS 及全平台超时/401/安装旅程仍需补齐，但作为缩小后的测试任务纳入。
- 下一步：按 DEV07 处理已接受的工程缺口或最小验证；不要把原始推测直接实现为权限/政策变更。

## 5. 与原工程报告的合并关系

| 原工程发现 | 合并后负责任务 | 是否保留原证据 |
| --- | --- | --- |
| R01 本地并发丢写 | DEV03 | 保留 100 次写入仅持久化 1 份的隔离实验及多进程缺口 |
| R02 人工批准边界 | DEV02、DEV18；新增 S2a/S2b | 保留源码结论；新增 HTTP 无认证凭据暴露，远程链仍待验证 |
| R03 Python/Go 签名 | DEV09 | 保留合成向量证据，扩展 manifest/未知字段合同 |
| R04 uploaded 卡住 | DEV10 | 与 Edge 幂等/重放设计一起处理，保持可恢复 |
| R05 事件 ID 为 null | DEV11；扩展 M-P2 路径 | 保留既有两处实验，新增路径逐一验证 |
| R06 UI 审批部署断点 | DEV13 | 不被安全清单掩盖，保留企业治理旅程 |
| R07 配置读回冒充强制生效 | DEV13、DEV18 | 作为发布可信表述门禁 |
| R08 安装备份损坏 | DEV07；合并 H4 | 保留重复安装与坏 JSON 实验 |
| R09 receipt 竞争 | DEV03；合并 M-G3 | 保留 race 证据，不扩大到所有半行读场景 |
| R10 模型输出校验/追踪 | DEV14 | 保留合成 provider 错误与缺失运行元数据证据 |
| R11 API 假成功 | DEV13 | 保留 200 HTML 与响应正文超时证据 |
| 原报告后续性能/队列/发布/文档项 | DEV03、DEV12、DEV13、DEV16、DEV17、DEV18 | 保留“建议/缺口”层级与未验证条件 |

后续审查者应先看本附录的具体反证，再看任务的验收表。不得仅按两份报告中重复出现的次数提高严重度，也不得把相邻弱点替代尚未成立的原攻击链。
