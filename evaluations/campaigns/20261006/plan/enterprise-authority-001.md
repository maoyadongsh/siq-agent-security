# 企业真实目标独占与当前授权测评预注册001

状态：拟执行协议，非测试结果。继承企业链004已经验证的原生发现、审批、实际网络收紧及回滚路径。只使用本批创建的PostgreSQL、API、OpenShell网关、sandbox、receiver和测试租户；不修改现有业务系统。

## 产品事实与问题

ADR0053、`target_authority.py`规定同一连接指纹和精确目标只能独占分配，授权文件逐请求读取；共享沙箱的交集授权尚未实现。`bindings.py`在同租户同backend/target上拒绝重复绑定。`deployment_impact.py`仅描述登记绑定，共享占用unknown、Skill隔离not_established、execution_confirmation_supported=false。因此本批验证独占及拒绝边界，不能宣布实现多Skill共享隔离。

此前单目标测试不能回答：另一资产能否抢占相同目标；授权文件失效后旧预览或旧部署回执是否仍能写入；影响报告是否夸大覆盖面。本批针对这些缺口设计，不重定义自然攻击成功率。

## 固定环境与样本

- 固定候选`5470ab3780f2-governancefix1`，API/原生Edge/Hermes Connector同候选；沿用已记录的Go二进制摘要。
- 生产模式API、PostgreSQL17两次迁移、RS256/JWKS测试身份、两个合成租户；无真实客户IdP保证。
- OpenShell v0.0.104真实mTLS网关，单个owned sandbox与receiver；原生扫描资产用于部署，另一合成资产仅用于抢占绑定探针。
- 共113项评测器显式HTTP（原企业链97+本批16），不含原生Edge内部HTTP；16个新增专项断言。所有请求预分配且不自动重试，失败仍保留。
- 模型调用0；本批的9次sandbox业务请求是同一任务的顺序阶段，不是9个独立攻击任务，不增加S4独立任务数。

## 执行步骤与预期

1. 运行原企业链到合法授权下的部署预览，保留已审批change、精确binding和独立策略读回。
2. 给另一资产创建原生实例，尝试同环境同后端同目标绑定：应409 `binding_target_conflict`，绑定/策略/部署/变更状态及真实后端策略不变。
3. 用当前preview_digest请求影响报告：登记的asset/instance/env/binding与原生资产相符，预览一致，覆盖面保持上述四项限制。
4. 顺序注入6种部署管理员文件状态，每种重新调用preview：删除文件、空分配、有效格式但已过期、错误asset、错误gateway摘要、不同tenant的重复连接/目标分配。每次应409 `deployment_target_authority_unverified`，数据库核心状态及后端版本/策略不变。每次归还原字节，不缓存授权，不以SQL写入模拟审批。
5. 换为同主体但不同assignment id的有效授权清单，用旧preview_digest提交：应409 `deployment_preview_changed`且无状态/策略效果。恢复原字节后继续原企业链的正常提交。
6. SIQ真实部署收紧策略，配置读回与接收端业务请求确认限制生效。
7. 在effective部署上重复步骤4的6种文件故障，每种尝试rollback。当前产品预期502 `openshell_rollback_failed: <digest>`，新增一条rollback_fail审计；核心状态仍effective，后端版本和策略不变。每次用新nonce从同sandbox真实curl到receiver：客户端非0，receiver业务到达0，独立健康控制成功。HTTP错误码本身不能作为防护成功证据。
8. 恢复原授权，执行原正常rollback：应200，策略内容恢复、正常请求到达1且返回正确nonce。继续原链的旧receipt mismatch、真实策略漂移拒绝旧preview、网关不可达检查。
9. 清理所有本批资源，保存原始捕获/协议/清单摘要，离线重新计算结果；输出白名单导出包，私有凭据不导出。

## 证据与判定

每个拒绝样本保留请求/响应、文件状态内容及摘要、数据库核心状态前后、独立OpenShell完整读回前后。回滚额外记录新增审计、业务CLI原始输出、receiver日志及健康控制。成功基线与恢复同样要求实际到达和返回内容正确，避免“receiver故障等于安全”的伪通过。

评分器必须用负向数据验证：接受重复绑定、夸大共享隔离、核心状态改变、后端策略改变、旧授权成功、伪造故障状态、回滚后仍有业务到达、receiver不健康、错误sandbox/receiver、审计缺失、nonce复用均不得全通过。预注册和运行证据只追加；失败不得覆盖为成功，调整后另编号。

本批不测试跨检查/写入间瞬时竞态、不保护服务UID管理员、不证明两个共享业务并存的隔离、不证明真实模型自然攻击增益，也不等于独立第三方认证。顺序文件故障由评测器显式控制，不能冒充自然生产事故。

## 可执行入口

从项目根目录使用`third-party-evaluation/20261006/private/candidates/5470ab3780f2-governancefix1/apps/control-api/.venv/bin/python`：

```bash
python benchmarks/third-party/enterprise_authority_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-authority-001-protocol
python third-party-evaluation/20261006/protocols/enterprise-authority-001-protocol/harness-source/enterprise_authority_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-authority-001-protocol --run-id enterprise-authority-001
```

运行输出提供manifest摘要；用同冻结目录的`verify_governance.py verify`及`export`复核，指定`--expected-manifest-sha256`，保留内部自测与外部见证的区别。
