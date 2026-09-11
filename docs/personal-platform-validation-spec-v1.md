# 个人平台实测材料规格 v1（UX-001 / K002）

日期：2026-09-11。状态：本批验收工具规格；不改变运行时协议和授权算法。

依据：[原任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md) §7、UX-001/002、AC04–06/AC11、§13；本规范补充[现有开发规格](agentshield-dev-spec-v1.md)的平台验证方法，不覆盖其签名、CAS、权限或状态目录规则。索引：[当前交接](personal-experience-current.md)。

## 1. 数据与证明边界

输入合同为 `packages/contracts/personal-platform-acceptance.v1.schema.json`，输出合同为 `personal-platform-acceptance-report.v1.schema.json`。它们只属于离线 QA 材料，不是 Grant、Intent、permission-fact 或运行时 API；任何运行时、UI 或发布脚本都不得据此自动授权或宣布 supported。

`platform_acceptance.py` 实现 init / verify 两个标准库命令。init 不检测平台，只生成全部 not_run 的待测表。verify 检查操作者声明的 candidate、测试方法、组合完整性、文件摘要和引用关系。摘要一致不证明证据正文真实、更不证明宿主实际执行；审阅者还必须查看原日志、宿主版本、执行入口和副作用。不能通过给旧日志改一个 candidate 字段冒充新测试。

本批采用原任务书建议架构形成 **18 个候选测试组合**：三平台分别列 Windows amd64 native/WSL2、macOS arm64/amd64 native、Linux amd64/arm64 native。它是待核实清单，不是最终支持矩阵，不宣称 WorkBuddy 有 Linux/WSL 版本。最低 OS、更多架构及不存在运行形态的产品裁决仍由 UX-001/Q01/Q02 产出。不得删除尚未验证行来制造全绿；调整候选清单须显式规格/合同更新和产品范围决策。

## 2. 每行需要记录什么

平台仅允许 openclaw、hermes、workbuddy；CodeBuddy 不能代替 WorkBuddy。每行独立记录 os/arch/mode、实际 OS 和宿主版本、实际受测 SIQ 二进制 SHA-256；WSL2 还需 guest_version，并将 os_version 保留为 Windows 主系统版本。没有运行的版本/二进制值为 null，不猜测。

八项能力是 UX-001 的接入探测，不替代 UX-015 的全旅程：discovery、normal_execution、pre_execution_denial、service_unavailable_denial、approval_resume、final_parameter_recheck、skill_attribution、install_interception。含义分别为发现、正常执行、执行前拒绝、决策服务失联拒绝、批准后恢复、最终参数复核、可信 Skill 版本归属和原生安装入口拦截。

每项必须包含 status/method/reason/evidence。状态为 not_run、blocked、pass、fail；跳过不作为通过。方法区分 none、source_review、component_fixture、native_cli、native_desktop。pass/fail 必须有非空证据及实际版本/二进制身份；pass 的 reason 必须 null，fail 为 observed_failure；not_run 必须 none 方法和空证据。blocked 保留明确类别，不产生通过。

native_cli / native_desktop 的 pass 只记为 native_checks_recorded；WorkBuddy 只有其本身 native_desktop 记录达到本探测的目标强度，CLI/CodeBuddy/网页夹具都不替代。八项全满足也仅输出 ready_for_review，support_claim 始终 not_assessed。未知归属、平台缺能力、缺系统环境均保留 needs_native_evidence；这不是 CI 代码失败，不阻止相互独立的后续实现。

## 3. 文件、安全与预算

manifest ≤512 KiB；18 行均须存在，每项最多 4 个证据引用。每个证据文件 ≤8 MiB，总独立读取量 ≤32 MiB。证据只能来自操作者指定的私有、稳定、不被并发修改的目录。路径为相对路径，拒绝点段、绝对路径、Windows ADS/设备名、反斜线、符号链接/重解析点、硬链接与特殊文件；只读指定 .json/.txt/.log/.png，不导入、不执行、不递归扫描用户目录。

引用必须匹配实际文件 SHA-256。同一内容不得跨目标组合借用；同一组合内多个检查可引用同一份完整报告。unknown 字段、重复 JSON key、错版、脏候选、漏项、摘要失配均返回固定错误类别，不把原输入或路径放入错误消息。

工具只在 --out 明确指定时排他创建新文件（POSIX 0600）；不自动建目录，不覆盖旧证据。普通 verify 的 0 表示材料结构/摘要一致；`--require-native` 在仍有缺口时退出 3；无效输入退出 2。输出写入成功但有缺口仍返回 3，应保留该真实结果。

校验器 **不是秘密扫描器或 OS 沙箱**。输入证据须先按仓库导出规则脱敏；文件内容不会出现在输出，但摘要检查不保证其中没有秘密。同 UID 恶意进程、根目录并发替换、伪造测试正文、操作者谎报方法都不在真实性证明范围内。单元测试中的“全部通过”矩阵只是合成夹具，禁止登记为平台实测。

## 4. 验证与兼容

JSON Schema 负责结构，Python 负责组合唯一性、平台独立、引用、预算与读文件语义；两者共享正向/负向样例与生产者输出测试。工具不读取旧签名对象、更不改写历史 evidence。旧 M1–M34/K001 的证据继续保留原身份，当前重跑材料用新 candidate。

CI 三系统运行的是验证工具自身的单元测试，不是目标智能体实测；Ubuntu 使用现有锁定 jsonschema/ruff 依赖补合同与 lint。`init → verify --require-native` 必须返回 3，用以防止空模板被误判验收完成。
