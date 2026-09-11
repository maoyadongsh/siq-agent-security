# ADR-030：基于当前授权起草与实例权限换发

- 日期：2026-09-10；状态：草稿及 Linux Hermes 换发已实现，跨平台任务继续实施；对应 UX-007、012。

现有创建接口按准入内容和实例复用 live Grant，不能用于编辑已批准授权。新增管理操作 `POST /v1/grants/{id}/draft`，请求 `grant-draft-create/v1` 明确源授权版本、操作者与客户端随机 request_id。源授权签名必须有效，仅 approved/deployed/effective/revoked 可作模板；到期授权可起草，但到期时间原样保留，必须显式修改并重新批准才能运行。

草稿使用独立 Grant/DesiredPolicy 标识与版本，保留主体、准入引用、资源/工具范围、拒绝、人批条件、模式和期限。深拷贝配置，不改原 Grant、策略、身份或绑定。清除 approved_by/effective_readback；effective 事实降为 declared，其他非 declared/inferred 事实降为 inferred，清除后端 authority_revision/readback_evidence_id，不能继承运行生效证明。原事实证据仅为模板来源，不证明新配置已生效。

接口响应 `grant-draft-created/v1` 包含源 ID/版本、新 Grant、当前 state_revision 和 reused。相同源版本、操作者与 request_id 导出相同草稿 ID，重试读回同一草稿（包括后续编辑状态），不覆盖。不同请求可创建独立草稿。源版本检查与新草稿审计/策略/发布复用 state commit 锁，避免源已变化后仍以旧版本创建；新审计记录源 ID、版本及请求标识，不记录凭据。缺失/重复/大小写别名/null/未知字段拒绝；16 KiB 上限。

界面保留旧身份时允许准备和批准新草稿；在旧身份明确停用前，不签发第二个有效身份。停用提示将阻止后续工具调用；发行新身份和配置接入仍使用 ADR-028/029 的明确确认与恢复流程。失败时不自动复活旧身份。用户应重新开启原平台会话；不能把旧会话 ID 无条件交给新身份，历史回执仍可验证。旧 Grant 可作为历史模板保留，不将新草稿状态写回旧授权。

本项不建立实际 Skill 加载归属，不等于三系统/三平台验收；其他平台、通知审批和完整权限模板继续按原任务书推进。

## 准入签名兼容修复

源准入须存在、可验签且非 quarantine。发现既有存储/CLI 导出在签名后补写 `skill_card_ref`；新写入不再改签名正文，卡片仍位于既有同名文件位置，字段可为 null。旧状态记录仅在路径精确等于该状态目录中由 admission_id 派生的卡片路径时，允许将该字段恢复为原 null 再验原签名；其余字段不归一化，未知路径、其他字段篡改、错误密钥均拒绝。历史文件不改写，也不将任意导出路径视为可信。此兼容明确只覆盖旧本机存储变换，不放宽通用 admission.Verify。

草稿中缺失的事实 evidence_ids 使用 `source_grant:<id>` 指向真实签名源授权，不生成虚构运行证据。原静态证据引用保留，effective 标记和后端读回引用清除。


## 验证

[M14 验证记录](../evidence/personal-experience/permission-revision-20260910/verification.json)绑定源码、四目标制品、Go/Python/Web 检查、浏览器与原生脚本。实际回执分类单独登记：普通调用/自检与换发调用的 decision/observation 不和 pending 拒绝补记混算；补记摘要逐条对应本机拒绝原记录。历史 M13 证据保留原制品身份。
