# 剩余改动整合记录（2026-10-07）

## 基线与结论

本轮以 `main@2caad03255efb72f97025df3126cd060de86ebf9` 为基线，核对原本地分支 `codex/windows-workbuddy-product-repair-20260928@5470ab37`、未提交文件及未进入 main 祖先链的远端分支。原分支 HEAD 本身已是 main 的祖先，落后 54 个提交；“本地文件与 main 不同”不能直接推断为主线缺少功能。

核对时，原工作区有 83 个修改的已跟踪文件、8 个删除项和 24,366 个未跟踪文件。其中 50 个修改文件与 main 已逐字节一致，8 个删除项与 main 一致，2,506 个未跟踪文件在 main 已有相同内容。33 个已跟踪差异需要语义审查；其余 21,860 个未跟踪差异主要是本地测评原始材料，其中 21,781 项位于既有测评批次。此计数是本地工作区盘点，不是新增产品功能或测评通过数。

用户要求只提交有价值的增量。主线已有 PR #110/#111 的 Windows 修复、后续版本合同和 PR #120 的目录整理，因此不把早期草稿整体覆盖到 main，也不重新提交生成于旧源码的前端制品。

## 纳入的增量

| 原草稿方向 | 当前缺口与最终处理 | 验证 |
| --- | --- | --- |
| 管理台身份与 Grant 联合读回 | 原界面仅凭 issued 身份及路径 profile 匹配就可暴露接入预览身份。整合到现有 managedReadback：还需匹配平台、主体、Grant/admission、部署状态和明确有效的到期字段。null 表示无到期，缺失/非法为未知；不按身份年龄推算会话到期 | 已部署/生效正向；缺失、未部署、撤销、期限边界、身份/平台/主体不匹配负向。服务端 Authority 仍为执行事实源 |
| WorkBuddy 预检错误分类 | 主线已有私密对象预检，但管理 API 将其变为笼统错误。仅将固定类别转换成可行动的 409 提示；未知类别不透传，事务恢复/计划变化仍优先 | 固定类别正向；未知类别、包装错误中的私密内容不泄露；需恢复的事务不能误标无需恢复 |
| 未映射工具边界 | 将旧草稿中 memory/read_memory 两个未知效果反例补入现有 runtimeaction 测试；Grant 不扩张已被主线长度及正反向断言覆盖，不重复补测试，不改变生产映射 | 最小 Grant 不扩张；未映射工具仍为 unknown effect |

## 不纳入的旧实现

| 旧草稿范围 | 主线覆盖及不合入原因 |
| --- | --- |
| client-install、状态迁移、Windows profile | 主线 `initialize.go`、`state_migration_binding.go`、`migration_diagnostic.go` 已覆盖并保留 EXE/目录绑定与恢复约束；旧实现会删除这些约束 |
| privatefs、WorkBuddy 安装事务、hook、关联锁 | 主线共享 `workbuddy_preflight.go`、Windows 私密发布、SDDL 保留和有期限锁等待已经落地；旧实现缺少后续安全复验及 Windows 锁释放修复 |
| pending v2、receipt、本地失败合同 | 主线 `pending/local.go`、`runtime-receipt/v2`、`test_workbuddy_pending_contracts.py` 已覆盖，并保留 unknown observation、原始事件及兼容屏障；旧版本会改写已发布 v2 语义 |
| start/stop help、runtime 展示 | 主线只读 help 和 scheduler_running/health=unverified 已实现；不重复引入另一套入口 |
| UI 草稿其余内容 | 保留主线的部署修订读回、同步提交锁、unknown/null 语义和工具边界说明；不恢复旧版读回逻辑及旧打包文件 |
| README、导航、扫描器旧差异 | 保留 main 的报告导航、来源绑定迁移守卫与扫描器回归；不删除已合入内容或为格式差异重复提交 |
| 本地历史计划、视频制作交付、截图、测评原始数据 | 保留本地原文及备份，不作为新的代码或新测评结果提交；公开报告及来源清单仍以 evaluations 中已发布材料为准 |

逐文件处置映射见 [审查清单](remaining-work-integration-20261007.json)。原文件、未提交 patch、状态清单和摘要校验清单位于本机 `var/remaining-integration-20261007/`；测评批次可复用上一轮已校验的只读备份。忽略的私密状态保持原位，不纳入公开清单或提交。

## 远端分支与 PR

- PR #109 只删除 README 中的一句徽章说明。`git cherry origin/main origin/maoyadongsh-patch-1` 为等价补丁，当前 README 已无该句；按已覆盖处理。
- PR #68 的 Cursor 环境曾以相关整合提交进入历史，并在 `3f5fca06` 明确回退。当前提案仍含未固定版本的远程安装脚本，且本轮没有新增 Cloud Agent 环境需求；不恢复该配置，保留原分支历史。
- 六个历史 Windows 分支中，17 个非祖先提交有等价补丁。剩余资源 profile、任务切换两项合同提交在主线分别由 `b3354219`、`e6e9db77` 及后续版本维护覆盖；与这两个对应整合提交比较，仅汇总开发规格文档存在差异，其余代码、合同、夹具和专门规格逐字节相同；主线随后继续演进，不能按旧文件覆盖。
- PR #119 的 SECURITY 版本修正已由 #120 收录并关闭；不重复合并其单独提交。

本轮不删除远端历史分支，不重写历史，不修改发行包或冻结测评证据。关闭被覆盖/不采纳的提案不表示其代码被重新合并。

## 验证与边界

- `npm ci`、前端全量测试（113 个文件、1,018 项）、`npm run build`、`npm run build:local` 均通过；嵌入资源由当前源码构建，旧文件不混用。
- `gofmt -l .` 无输出；`go vet ./...`、`go test ./...`（44 个含测试包通过）、新增 API 回归的 `-race` 均通过；Linux amd64/arm64、Darwin arm64、Windows amd64 四目标构建通过。
- 将 API 实现临时映射回基线的负向复查中，新测试因缺失预检类别而失败；当前实现通过。旧草稿不直接成为测试夹具或产品实现。
- 仓库守卫及 20 项仓库测试通过。密钥扫描和远端 CI 按最终提交检查，结果见对应 PR；不将未结束的任务提前记为成功。

组件回归不等同于一次新的 Windows WorkBuddy 原生业务测评；历史证据与新版结果分开记录。
