# Windows WorkBuddy 合入 main 复核

结论：修复分支可以作为完整合并单元，但应先补入本次复核的两项状态读回修正，完成新提交的检查和审核，再合入 main。代码合入与正式发行、原生业务验收分开；不能据 CI 绿色宣布 Windows 产品修复完成。下文为初次复核快照，当时尚未提交或推送。

后续执行授权：用户已要求“按照你的建议修正合并”。本次将已验证小修追加到 Windows 分支，保留原工作区，并新增 Windows 原生组件 CI：专门回归必须成功，完整模块与同工具链精确 base 比较并保留所有失败及 skip；新的失败、构建失败、无结果及不完整运行拒绝通过。基线失败不改称完整通过，新 skip 单列待审查。该 CI 不执行 WorkBuddy 桌面或模型，不是专用宿主业务验收。审核与分支保护保持原样，正式签名另行执行。

## 固定对象与合并方式

- main：`4c978aff905420b758d9ba3c7713069fdce305ab`。
- Windows 分支：`codex/windows-workbuddy-product-fix`，HEAD `83369e83b5b2123c696cee12e4cf58bc0d292791`。
- [PR #110](https://github.com/maoyadongsh/siq-agent-security/pull/110)：OPEN / DRAFT，GitHub `MERGEABLE`，但 `BLOCKED / REVIEW_REQUIRED`。
- main 已是 Windows 分支祖先，无须为了当前基线 rebase。11 个提交、157 个差异文件；`git merge-tree --write-tree origin/main HEAD` 退出 0，结果树与 Windows HEAD 树均为 `95d597fbdf693892970289de9ed7f367f11956ab`。
- 本地复核分支 `codex/windows-workbuddy-merge-review-20260928` 从上述 Windows HEAD 创建，工作树位于 `/home/maoyd/siq/worktrees/windows-wb-submission-review-20260928`。补丁尚未提交；原开发工作区及其用户改动保持原样。

建议在 PR #110 追加小修后采用 **merge commit**：保留 Windows 11 个原始提交哈希与已有证据映射，容易整体审查及源码回退。仓库允许 merge commit，未要求线性历史。不要只 cherry-pick 最新的导入夹具提交，也不要拆掉共享合同与读写器兼容检查。若 main 又前进，需重新固定 base/head、模拟合并并验证最终代码树，不能沿用此处树哈希。

当前 main 保护要求：严格最新基线检查、31 个必需检查、1 个批准以及 CODEOWNERS 审核，陈旧审核自动作废。应走正常审核，不使用管理员绕过保护；本次未修改这些规则。最新推送后旧 CI/审核不能替代新 HEAD 的结果。

## 复现发现及局部修正

### M1：历史运行失败错误地否定本次配置修复

`apps/web/src/local/managedReadback.ts` 原先拒绝所有 `checks[].status=fail`。服务端在配置状态之外追加 `hook_load`，它可能仍是上次失败的原生自检。因此 Hermes、OpenClaw、WorkBuddy 配置本次已正确写入和读回，仍会被新增前端逻辑报告应用失败。这不是未经复现的前端持久化假设。

复现：`npm test -- src/local/managedReadback.test.ts`，新增实际诊断形状场景后退出 1。修正仅将历史 `hook_load` 与配置应用判定分开，保留它的 fail 和 runtime unverified；身份、配置及其他检查失败继续拒绝成功确认。正负向测试含三个平台及撤销身份拒绝；修正后退出 0。

### M2：WorkBuddy 正常卸载保留宿主 settings，却读回 incomplete

已有卸载保留第三方设置与 hook，这是正确行为。但后端诊断看到 settings 存在、SIQ hook 缺失就报告 incomplete。该分支新增的卸载读回强制要求 not_installed，因此把真实成功卸载报成失败。

复现：`go test ./internal/adapterinstall -run '^TestWorkBuddyUninstallReadbackPreservesHostSettings$' -count=1`，退出 1，得到 `ConfigurationState:incomplete`、`host_registration:fail`。修正后仅当最新卸载已提交、密封计划认证通过、实例根一致、当前全部操作文件匹配卸载后镜像时返回 not_installed。保留用户 settings/第三方 hook 的原始字节；不修改 ACL，不恢复身份，不读取凭据。

新增负向验证：篡改密封计划、篡改结束记录、缺失结束记录、重新写回 SIQ hook 均不能靠历史卸载宣称成功。额外补充 Windows managed uninstall 诊断断言，已交叉编译但尚未在 Windows 执行。规格更新于 `docs/workbuddy-managed-runtime-spec-v1.md`。

## 影响面与兼容边界

| 部分 | 对主线的影响与结论 |
| --- | --- |
| ACL/SDDL/单链接规则 | Windows 实现与只读预检保留原私有边界，不默认修改宿主 DACL；Linux 编译与测试不能证明 Windows ACL 行为 |
| pending/v2 与 receipt/v2 | 是共享协议变更，需与生成、提升、展示、schema 和 reader/writer 4 一起合入；旧 v1 样例/签名字节保留 |
| 旧版本回退 | 当前发行工作流发现 v2 历史时拒绝能力小于 4 的候选；旧 marker 不会自动阻止用户直接运行旧二进制。不能把源码 revert 当成已写状态可降级 |
| 安装事务、inventory、Grant 初次提交、HEAD 提示 | 涉及共享代码，已跑 Linux 完整模块和相关 race；HEAD 仅可重建提示，checkpoint 失败仍需拒绝 |
| 前端 | 安装、批准、部署、运行自检仍需分开；本次 M1/M2 专门修复新增读回与既有后端状态不匹配 |
| 工具能力 | 没有把 present_files/Glob/Grep 默认为 Read，没有扩业务 Grant 或自动续期 |
| CI/发行 | 现有 Windows job 标注构建输入检查，不是原生验收。合入 main 会触发适用 CI/Pages；正式发行签名由独立 workflow_dispatch 执行，不因合并自动完成 |

已核对当前差异不修改已有正式签名制品。Windows 历史 J-02 根因不从并发组件复现反推；新的组件锁竞争结果与历史现场继续区分。

## 本机实际验证

环境：Linux arm64，Go 1.26.5，Node 22.22.2，npm 10.9.7。下列 Go 命令在 `apps/agentshield`，npm 命令在 `apps/web`，Python 命令在仓库根。未运行 Windows/macOS 原生测试或 WorkBuddy 桌面模型任务。

| 代码对象 | 命令 / 检查 | 实际结果 |
| --- | --- | --- |
| 原 Windows HEAD | `git diff --check origin/main...HEAD`、merge-tree | 退出 0，无合并冲突 |
| 原 Windows HEAD | `go test -count=1 -timeout 10m ./...` | 退出 0，完整模块通过 |
| 原 Windows HEAD | `go vet ./...`、`gofmt -l .` | 退出 0，无格式输出 |
| 原 Windows HEAD | `go test -race -count=1 ./internal/workbuddycorrelation ./internal/pending ./internal/receipt ./internal/adapterinstall ./internal/state` | 退出 0，5 包通过 |
| 原 Windows HEAD | `npm ci --no-audit --no-fund`、`npm test` | 退出 0，113 文件 / 1,015 测试通过；ci 安装命令未执行 audit |
| 原 Windows HEAD | `npm run build`、`npm run build:local` | 退出 0，重建嵌入资源与提交一致；local 主包超过 500 kB 有提示 |
| 原 Windows HEAD | Python schema / release 单测（见下） | 退出 0，收集总数 300（286 + 3 + 11） |
| 原 Windows HEAD | Linux amd64/arm64、Darwin arm64、Windows amd64 构建 | 全部退出 0 |
| 补丁后 | `go test ./internal/adapterinstall ./internal/server -count=1 -timeout 10m` | 退出 0 |
| 补丁后 | `npm test`、`npm run build`、`npm run build:local` | 退出 0，113 文件 / 1,016 测试通过，嵌入资源已按正式命令重建 |
| 补丁后 | `go vet ./...`、格式检查；Windows adapterinstall 测试交叉编译 | 退出 0，原生运行未执行 |
| 补丁后 | `go test -race -count=1 ./internal/adapterinstall` | 退出 0，13.922 秒 |
| 补丁后 | 四平台重新构建（含最新嵌入资源） | 全部退出 0 |
| 补丁后 | `go test -count=1 -timeout 10m ./...` | 退出 0，44 个包通过，8 个包无测试文件 |

Python 实际命令：

```sh
/home/maoyd/siq/siq-agent-security/apps/control-api/.venv/bin/python -m pytest --noconftest apps/control-api/app/tests/test_workbuddy_pending_contracts.py apps/control-api/app/tests/test_schema_contracts.py scripts/release/test_package.py -q
```

构建命令（四个 target 为 linux/amd64、linux/arm64、darwin/arm64、windows/amd64）：

```sh
GOOS=${target%/*} GOARCH=${target#*/} CGO_ENABLED=0 go build -trimpath -o /tmp/siq-wb-merge-review-${target%/*}-${target#*/} ./cmd/agentshield
GOOS=windows GOARCH=amd64 go test -c -o /tmp/siq-wb-merge-review-adapterinstall.test.exe ./internal/adapterinstall
```

远端 PR 检查已执行项均 SUCCESS；deploy、SonarCloud Code Analysis、runtime-security-nightly 为 SKIPPED。不能把 skipped 计作通过。原分支 CI 结果不包含本地补丁。

补丁后本地日志：`/tmp/siq-wb-merge-review-go-test.log`、`/tmp/siq-wb-merge-review-race.log`、`/tmp/siq-wb-merge-review-web-build.log`。可移交 diff 为 `/home/maoyd/siq/worktrees/windows-workbuddy-merge-review-20260928.patch`，基于 `83369e8`，包括本次规格、代码、回归、重建资源和本报告；在干净且固定该基线的工作树中先执行 `git apply --check <patch>`，再应用和验证。补丁不是已提交或已签名制品。

## 合并前与发行前门槛

1. 将本次小修连同回归、规格和重建资源追加到 Windows PR 分支，固定新 HEAD。不要合并原本地未完成的产品重写草稿。
2. 新 HEAD 重跑 PR 的必需检查；复核最终 base/head 代码树。申请正常 CODEOWNERS 审核，下述 Windows 补验及审核条件齐全后才 merge commit，不以原分支 CI 代替补丁后的检查。
3. 在专用 Windows 实例对同一新 HEAD 运行完整 `go test -p 2 -count=1 -timeout 10m ./...`，保留 stdout/stderr/退出码及 skip。对剩余失败按同工具链的 main 对照逐项归因；修改范围不能有新增失败。此处不能以“都是基线失败”笼统豁免。至少执行新增卸载测试以及现有 managed ACL/回滚/并发/初始化测试。
4. Windows 既有交付记录最后一次完整运行仍是 `84076cf6` r14：53 个包结果、8 个失败包、19 个顶层失败名；`83369e8` r15 是定向通过。原始 Windows 日志未在本工作树，不把文档记载当成此次亲自运行的结果。应补最新源码完整结果和脱敏索引。
5. 代码合并后仍保留“Windows 原生验收未完成”。正式候选使用新的版本/签名，执行专用 WorkBuddy 新批次 N、R/W/T、J 三轮、F-down/F-up、安装升级重装卸载及并发恢复矩阵。不得拿历史 A/S 或组件模拟替代同期原生任务。

Windows 定向补验命令（命令准备，不代表已执行）：

```powershell
go test -count=1 ./internal/adapterinstall -run 'TestWorkBuddyUninstallReadbackPreservesHostSettings|TestWorkBuddyManagedInstallDiagnosisAndRevokedUninstall|TestWorkBuddyManagedPreflight|TestWorkBuddyManagedApplyRechecksACL|TestManagedConfigReplacementAndRollbackPreserveDeny|TestManagedFileNewPublicationAndDeletedFileRestore'
go test -count=1 ./cmd/agentshield -run 'TestWorkBuddyManagedConcurrent|TestFreshWindowsClientInitialization|TestWindowsInitialization'
```

源码出现回归时，可按 merge commit 回退相应代码；这不授权恢复旧状态目录。写入 v2 事件后，运行回退必须遵守 reader/writer 4 与实际事件历史检查，保留兼容二进制及原台账、Grant、撤销记录。操作卡见 `docs/windows-workbuddy-upgrade-recovery-20260928.md`。
