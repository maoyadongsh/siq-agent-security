# ADR-037：Skill 安装预览与私有暂存

状态：核心暂存与复验已实现并通过 Linux 隔离测试；UX-009 仍在进行，API/UI、目标写入、恢复与读回待继续集成。

## 目标与边界

在安装前，将已批准 Grant、完整导入来源、目标实例/目录和待写入清单固定在同一份签名计划中。复制、取消、超时或预览失败均不改变平台目录，不执行 Skill 或任何安装/生命周期脚本。M20 的导入权限仍不能通过通用 deploy/effective 激活；暂存完成不是已安装、已识别或已保护。

Hermes 官方文档将 profile 内的 `skills/` 作为默认 Skill 来源，profile 也隔离对应目录。本阶段只规划经现有实例解析器获得的 `<profile>/skills/<directory_name>`，不接收任意绝对目标路径；外部搜索目录或配置的写入目录不自动成为安装目标。来源：[Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)、[Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/)，2026-09-11 查阅。文档不是本机当前版本原生验收，后续需用公开 CLI 验证平台识别。

平台配置写入的 adapterinstall 事务保存配置前后图像和加密备份，不能直接代替完整 Skill 树的身份、清单和容量限制。本阶段复用 skillimport 的文件/目录/执行位清单、读取预算和无链接复制能力；安装状态由独立 skillinstall 包负责，避免将获取候选误作安装完成。

## 计划合同

`local-skill-install-stage-create/v1`：request_id（is-32hex）、grant_id、expected_revision、instance_id（hi-32hex）、directory_name、actor_id，全部必需。directory_name 是用户明确选择的单层可移植目录名，1–64 位小写 ASCII 字母/数字/连字符，首尾为字母/数字，Windows 设备名亦拒绝；不能覆盖已有路径或大小写别名。

`local-skill-install-plan/v1` 为签名只读计划：plan_id（sip-64hex）、request_id、source、grant_id/revision/signature/permission_digest、platform=hermes、instance_id、directory_name、target_locator_digest、target_display、actor_id、created_at/expires_at、file_count/total_bytes、installed=false、runtime_verified=false、signature。完整 source 使用 ADR-036 合同，target_locator_digest 是实际绝对目标路径 SHA256；target_display 由可信目标解析器产生供人审阅，不由客户端传入。

plan_id = SHA256(规范化 `{request, source, target_locator_digest, grant_signature, grant_permission_digest}`) 加 sip- 前缀。同请求在源/目标/授权不变时复验并复用原计划，不重置五分钟有效期；已过期时需要明确的新 request_id。权限 revision 或源变化时拒绝旧请求，不把旧计划当作当前批准。同一 request_id 的已发布计划通过有界签名元数据扫描查找，目标、操作者或请求字段改变时拒绝复用；已损坏或无法验签的计划使该次准备失败，不信任其请求身份。

## 暂存与复验

计划和载荷位于状态目录 `skill-installations/{plans,stages}/<plan_id>`；最多 64 个暂存候选，包括无法确认归属的孤立目录。先创建独占阶段目录，复制到 payload，完整重新核对暂存清单、原导入和最新 Grant，再最后排他发布签名计划。新建失败只清理本次创建的阶段目录，不接管同 ID 孤立目录。源与目标路径均拒绝链接/特殊类型，使用既有 2000 文件、2000 目录、8 MiB 单文件、64 MiB 总内容预算。

Grant 必须可验签、状态恰为 approved、未过期、revision 匹配，主体恰为目标 Hermes 实例的 hri 身份，来源 admission 必须通过 ADR-036 当前完整副本复验。比较完整 Grant 签名与 PermissionDigest，复制过程中撤权/权限变更使预览失败；完整载荷复验结束后再次读取授权版本/签名/期限并检查目标缺失。不调用批准、部署或身份签发。

Load 重新验证计划形状/签名/ID/期限、批准版本与来源、目标仍缺失、暂存及原导入完整摘要。元数据历史不等同于当前可安装。所有外部错误使用固定 skill_install_* 类别，不带原路径、文件正文或凭据。

本阶段不向平台目录写入，也不声称解决跨 OS 的整目录原子发布。后续 apply 必须独立设计创建归属、覆盖冲突、未完成状态、人工确认绑定、撤权竞态与目标读回；不得把 POSIX os.Rename 的“可替换空目录”误称为跨系统的 no-replace 原语。旧版本降级保护与可信 Skill 调用归属仍是完整交付要求。

## 验证

临时状态目录与虚构目标目录验证：批准/未批准/过期/撤销、错误实例/请求、目录名/大小写冲突/符号链接、独立文件副本与完整签名辅助文件、原源变化、暂存篡改、原计划重试/到期不续期、复制期间授权改变、故障清理与孤立目录保留。共用 Go 样例回灌 Python 合同与 ID 重算；交叉编译不能替代实际三系统文件操作验收。API、UI、目标写入和恢复将继续集成，尚未完成的阶段不计为安装完成。

## 本批实现与证据

实现为 `internal/skillinstall` 库及 `skillimport` 私有复制接口，目前尚未接入 daemon 路由和前端。计划只提供固定时点的签名预览；后续 apply 必须再次核验来源、授权和目标，不能将暂存当作持续有效的权限。跨进程使用仍需上层持有既有状态 writer 锁；进程内准备采用可取消串行入口。

[验证清单](../evidence/personal-experience/skill-install-staging-20260911/verification.json)记录 Go 核心与竞态测试、Python 合同、全量回归和四目标所有包编译。样例规范化了状态相关授权身份、分析时钟与目标摘要并重新签名，属于 DTO 合同夹具；不作为真实安装授权。暂存容量包含孤立目录，第 64 个可创建，第 65 个拒绝；历史清理生命周期继续留在 UX-010。交叉编译包括尚未接入命令的 skillinstall 包，不作为三系统文件操作实测。
