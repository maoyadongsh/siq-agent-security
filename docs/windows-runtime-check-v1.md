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

## 本次进程的合成模型路由

仅传 `--provider custom` 和 `CUSTOM_BASE_URL` 不足以隔离模型路由：实际 Hermes 会读取 profile 的 `model.api_mode`、`fallback_providers`、旧 `fallback_model` 及各辅助任务的独立路由。本增量沿已安装 Hermes 官方 `HERMES_MANAGED_DIR` 覆盖入口，在本次材料目录排他创建私密 `managed/config.yaml`（JSON 也是 YAML）；保持原 `HERMES_HOME`、实际 CLI、插件和实例身份，不修改用户配置，不改 v5/Grant/Binding 签名字节。

覆盖注册本次随机唯一的 named custom provider 和随机模型名；CLI 明确选择该 provider。主路由与已知辅助任务固定同一个含随机路径的 `127.0.0.1` 合成端点、`chat_completions` 协议及非凭据占位 key。两个主 fallback 键和每个辅助任务的 `fallback_chain` 都显式置空，关闭自动标题、后台 review 和压缩。子进程设置 `PYTHON_DOTENV_DISABLED=1`，不从用户 `.env` 覆盖本次环境；不采用会禁用 SIQ 插件的 safe-mode 或忽略整份用户配置。

覆盖文件在执行前后按本次创建的对象身份、私密权限和精确字节复验；在单次 native 子进程期间以现有 Windows 私密只读句柄保持文件及父链不可写入、删除或替换，退出即释放，不跨请求缓存授权结果。损坏、缺失、替换或不兼容即失败。native named-provider 解析能力不可用时，随机唯一 provider 必须以未知 provider 失败，不能回落到裸 custom/auto；本地合成服务不可用不能切到真实模型。启动前仍重查原实例快照，原 120 秒/45 秒预算不延长。

已有 `HERMES_MANAGED_DIR` 或宿主默认 managed 目录不能被静默丢弃。实现通过现有私密 native stage 的官方 `config get` 解析完整配置副本，保留既有 managed mapping 的全部非冲突键，并仅新增合成模型路由；已有管理员钉选与合成路由冲突时明确拒绝，不覆盖管理员决定。来源目录、配置对象/内容及原来不存在的入口都纳入启动前后复验。managed `.env`、环境引用或无法完整解析的 mapping 暂不支持，属于明确缺口；不能以一次孤立实例通过宣称一般 profile 已完成。

已安装 Hermes `env_loader.py` 会在 dotenv 库执行前整理 `.env`，还会独立加载 `secrets` 源及 managed `.env`；因此 `PYTHON_DOTENV_DISABLED` 不是这些入口的隔离证明。启动前只能检查这些文件是否存在而不读取凭据；profile 的 `.env` / `.op.env`、已启用秘密源或安装根开发 `.env` 未被安全排除时拒绝。配置解析仅在自有 stage 进行，空 managed 目录和插件元数据副本不会执行用户配置中的插件。未知辅助任务、额外启用插件、外部 memory/context provider 不能被宣称已覆盖；无法证明限定路由的配置须拒绝，不通过屏蔽原 SIQ 钩子获得通过。

Windows 原生入口目前只接受可静态核对的 uv PE/zip console launcher：单一固定 `__main__.py`、绝对 venv Python、PEP 610 editable `direct_url.json`、生成的 `.pth`/finder 中 `hermes_cli` 映射必须指向同一源码根。只读检查安装根 `.env` / `.op.env` 缺席，并复验实际入口、metadata 与源码入口身份；未知 launcher、多个 metadata、映射冲突或变化明确拒绝。此能力检查不执行 Python metadata，不猜相邻目录，也不声称完整依赖供应链已被证明。

原配置不得在 managed 合并后禁用 SIQ 插件或放开该插件的工具覆盖；`auto`/未选 provider 同时带自定义 `base_url` 的 profile 也暂不支持，因为已安装原生 resolver 会在未知 provider 错误之前尝试该 URL。环境文件的缺席复验仅用 `Lstat`，一旦出现立即拒绝，不能先读取新凭据内容。profile、既有 managed 来源和安装源仅执行前后身份/内容复验，不宣称抵抗任意同用户进程在执行中的瞬时篡改或任意 Python 依赖注入。

该配置控制仅覆盖已核实的 Hermes 主模型与标准辅助路由，不是操作系统网络隔离，也不证明任意第三方插件直接 SDK 请求被隔离。旧 POSIX 启动语义不变；组件及安装宿主的离线配置解析检查不得记作真实自检通过。正负向应覆盖云协议/主辅 fallback 原配置、冲突 `.env`、缺失/损坏/替换 overlay、本地端点不可用、已有 managed scope、未知辅助任务/额外插件及清理范围；不得发起真实模型请求来验证失败关闭。
