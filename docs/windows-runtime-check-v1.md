# Windows Hermes 运行自检增量

2026-09-18，延续 ADR-024、ADR-028 与 Windows 资源 profile。实现及组件验证不等于真实 Hermes 自检已通过。

## 已确认缺口与范围

旧自检把 Windows 原生探针路径写入 POSIX `intent/v2`，在启动宿主前失败；旧 `grant.Build` 还会携带 SkillRef，不能作为不证明 Skill 归属的实例自检权限。不能把旧签名路径改解释，不能冒称 `local-runtime-identity`，也不能撤销用户现有身份换取临时身份。

仅修复既有管理预览、明确确认、当前实际 Hermes 配置、独立 120 秒自检流程。POSIX 继续原 v2/rca 流程；不新增宿主、通用授权入口或模型调用。不改变已有 v2/v3/v4 签名字节、解析含义和自动会话。

## 合同与发行

新增 `intent-contract.v5.schema.json` / `intent/v5`，`authority_kind=runtime_check`、`filesystem_profile=windows-local-drive/v1`、`authority.issuer=local-runtime-check`。只允许 Hermes，`rci-` Intent、`rct-` task、`rca-` agent 共享本次 `rc-` 的 32 位十六进制后缀；authority.revision 为本次已确认目标快照摘要。只有 `read_file` / `file.read`、单个 filesystem prefix、空参数/来源/效果要求。资源必须是服务生成的 `<state>/runtime-check-materials/<check_id>/allowed` 的规范路径。issued_at=valid_from=本次开始时间，expires_at 不晚于开始后 120 秒；活动检查仍独立核对其原始截止时间。

v5 复用原 Intent 签名、存储、撤销与 matcher；绑定仍为 `intent-grant-binding/v2`，必须是当前签名 `grant/v2` 和 `grant-permissions/v2` 精确引用。普通 Intent 创建、普通 binding 创建拒绝 v5；原 managed enrollment 仍只发 v4。不存在 issuer 自报或仅按 ID 前缀得到执行权限的路径。

Windows 自检先验证状态目录已经由用户确认启用 Windows profile；不自动启用或迁移。目标来自可信 inventory / 已安装配置的 `InspectRuntimeTarget`，快照纳入 profile 和实际配置根身份；预览、确认、启动及最终检查重新核对。请求不接受 profile、磁盘、cwd 或材料路径。

`grant.BuildRuntimeCheckDraft` 仅接受真实已验签正常准入、本次固定模板名称/引擎、只读工具声明、Hermes、同后缀 rca 主体、服务器当前时刻起不超过 120 秒的期限。以本次 check ID 派生独立 Grant ID，在首次签名前创建无 SkillRef 的临时 baseline；不改写准入、现有 Skill Grant 或通用 BuildInstanceDraft 的 hri 边界。Windows 分支再经 `PrepareWindowsResources` 生成仅本次允许目录的只读范围，正常 challenge、ValidateChallenge、Approve、MarkDeployed 和带审计 CommitGrant。状态 profile、目录身份、签名、期限与撤销检查保持。

## 使用、观察与恢复

仅已确认且活动中的 Manager 拥有独立启动凭据；首次实际 session 附着后不能换会话。每次 decide/observe 鉴权须同时匹配活动状态、原截止时间、凭据、实例/目标快照、rca、session、Intent ID/digest/task/revision、binding ID 和精确 Grant 引用；重新核验当前 Grant 的 Windows profile 与文件身份。不能使用全局或普通实例凭据借用自检身份。

结束前重新核对当前绑定/授权及目标，核验两次允许读取、一次执行前写入拒绝、五条签名且关联一致的回执、拒绝目标不存在；取消和过期不能留下 passed。随后撤销 Intent、绑定、Grant，再清理本次材料。错误或恢复只清理，不复活权限；绑定已发布但 journal 尚未记录其 ID 时仍按本次 Intent 找回并撤销。当前普通 managed identity 不变。

本固定只读探针不申请独立文件观察者，不支持 `effect_requirements`；独立 file-observation API 对 v5 明确拒绝，不跳过或冒用 managed `VerifySessionAuthority`。普通 `/v1/observe` 继续按自检短凭据和当前完整授权复验。回执仅证明本次调用链，不升级 Skill 归属或历史 effective。

## 验证边界

新增合同正例、严格字段/版本混搭/主体/时间/资源/普通入口负向；固定签名样例使用公开测试 seed，不是正式发行签名。组件覆盖状态 profile 未启用、目标漂移、正常读/越权拒绝、当前授权撤销/替换/过期、目录替换、会话重放、观察与清理恢复。保留旧 v2/v4 向量及语义。最终真实宿主、完整回归和制品证据另行执行，开发树检查不得计入 303 项宿主验收通过。

组件测试的异步完成观察窗口从原 5 秒改为 150 秒：覆盖产品原有 120 秒上限及随后撤销清理，避免 Windows 文件身份与 ACL 复验尚未结束便误判失败；产品 `Duration`、签名有效期与每次在线过期检查仍固定不超过 120 秒。此调整不延长钩子 4 秒 HTTP 预算。
