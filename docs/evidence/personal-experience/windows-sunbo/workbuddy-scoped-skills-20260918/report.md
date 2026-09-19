# Windows WorkBuddy 用户级与项目级 Skill 开发检查

本包记录 2026-09-18 的功能开发及回归检查，不是干净发布候选、浏览器交互或原生 WorkBuddy 验收。所有检查统一标记 `source_dirty=true`：是在提交前或仍有其他开发改动的工作树运行。后续提交引用用于定位实现，不能倒推检查在该提交的干净树完成。

## 实现和版本边界

- 规格：`773279b414df0e981af70b3c5eeb61d7fb563192`。
- 合同：`aa5ddef2afa07b66e25455847b2093ea48ff51d8`。
- Go 实现：`2285309e7a035b1e8c4ea70ee15530c57a942d61`。
- Web 与 Go embed：`1122cf49534eed6e15af6da337031bc3f58aebdf`。

本轮实现明确区分用户级和已登记项目级目标，版本化 Plan/claim/record/update 引用闭包；目标来自服务端可信 inventory，不能由请求 cwd 或任意路径选择。安装、更新、移除、恢复继续沿现有事务，签入根及父链身份。更新固定原 scope、目标及根身份，只允许经旧事实链验证后推进父锚点。Web 明确选择目标，不把不可用项目回落到用户根；Windows 导入 Grant 保留来源和 Skill 身份，须另行确认资源解释。

`installed_unverified` 只表示文件发布和读回。实例权限准备仍是 approved 导入授权的专门路径；SEC/v1 只表示受控会话归属，不证明原生模型实际选择该 Skill、项目沙箱、原生缓存刷新或每调用因果隔离。静态样例用仓库公开测试种子，不能视为正式发布签名。

## 检查结果与失败保留

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| r1 Windows 导入 Grant profile | 2 个顶层用例 PASS，exit 0 | `logs/go/r1/imported-windows-profile.stdout.log` |
| r1 新合同 | 22 个成功进度点、100%、exit 0；有既有 Starlette 弃用提示 | `logs/go/r1/workbuddy-contracts.stdout.log` 与 `summary.json` |
| r2 集成定向 Go | 整轮 exit 1；7 个顶层用例已明确 PASS，不能改写整轮/包失败 | `logs/go/r2/scoped-skill-integration.stdout.log` |
| r2 vet | exit 1，服务端 profile 类型不能直接用作 string | `logs/go/r2/targeted-vet.stderr.log` |
| r3 canonical 样例 | 1 个顶层用例 PASS，含原 v1、新 v2 项目/用户样例；exit 0 | `logs/go/r3/canonical-contract-vectors.stdout.log` |
| r3 服务端 | 6 个顶层用例 PASS，exit 0 | `logs/go/r3/server-scoped-installation.stdout.log` |
| r3 负向及恢复 | 4 个顶层用例 PASS，exit 0 | `logs/go/r3/scoped-installation-negative-recovery.stdout.log` |
| r3 五包定向 vet | exit 0，stdout/stderr 均空 | `logs/go/r3/summary.json`；空流摘要在 `provenance.json` |
| 最终 Web 类型检查 | `tsc --noEmit --incremental false`，exit 0 | `logs/web/types-r3.result.json` |
| Web 定向回归 | 8 文件、53 项通过，exit 0 | `logs/web/vitest-r2.log` |
| Web 全量回归 | 30 文件、217 项通过，exit 0 | `logs/web/full-regression-r1/stdout.log` |
| 企业及本地构建 | `npm.cmd run build` / `build:local` 均 exit 0；24.384 / 25.079 秒 | `logs/web/build-r1/` |

r2 有三类明确失败，均保留原始脱敏记录：

1. `TestWorkBuddyV2CanonicalContractVectors` 的三个样例报 `independent signature or exact typed bytes changed skill_install_changed`。根任务定位为测试 canonical helper 的 JSON 数字解码方式错误；r3 改用 `canon.Decode` 后通过，未放宽验签或改签旧正式文档。日志本身记录失败症状，原因依据实现负责人定位和修正后的 helper。
2. `internal/server/skill_install_targets.go:144` 的 `FilesystemProfile` 到 `string` 未显式转换，导致 server build 与 vet 失败；修正后 r3 服务端与 vet 均通过。
3. skillinstall 包在总计 180 秒预算耗尽时触发 `panic: test timed out after 3m0s`，不是剩余用例已经完成。后续拆分 canonical、server 和负向恢复组，分别使用 60/240/480 秒的开发测试包预算；没有扩大产品 WorkBuddy 4 秒 HTTP 或安装检查预算。r3 负向恢复命令耗时 187.771148 秒。

独立解析 Go JSON `Action=pass`，按 `(Package, Test)` 去重并排除含 `/` 的子用例，共 **20 个唯一顶层用例完成 PASS**：grant 2、skillinstall 8、skillcontext 2、server 6、inventory 2；新增来源 r1=2、r2=7、r3=11。逐项用例与日志行号见 `go-top-level-results.json`。这是一组开发检查的去重结果，不是单一候选或全包通过声明。

r2 已通过的双 scope 生命周期、controlled_session SEC 和 inventory 检查保留原 PASS，r3 没有重跑它们。实现未因 r3 helper/转换/测试预算修正而变化的依据是本轮实现负责人交接；本包不伪造 r2 的逐文件现场快照。`source-after-checks.json` 仅为检查后采集的源码摘要。

53 项定向 Web 检查已包含在后续 217 项全 Web 回归中，不能相加。20 个 Go 顶层用例、22 个合同检查、217 项 Web 测试及两个构建是不同统计口径；**本包没有修改 303 台账，也没有新增真实验收 PASS**。

## 构建与产物

两个输出目录在构建前已核对为本工作树下的普通目录，祖先没有 reparse：企业 `apps/web/dist` 为忽略产物，本地 `apps/agentshield/internal/ui/embedded` 为 Go embed。没有安装依赖、修改宿主配置或运行模型。

构建前后 144 个前端输入文件摘要一致。本地有 214 个文件，变化为 7 个带内容摘要的 JS 文件替换及 `index.html`，CSS 和字体未变。首页引用文件均存在，bundle 包含服务端 targets 路由与明确用户/项目选择文案；无源码映射文件，未发现本机私有工作区路径。精确变化、文件摘要和只读产物核对见 `logs/web/build-r1/summary.json`、`embedded.after.json`、`artifact-check.json`；本包不包含二进制或完整构建产物。

企业产品构建成功、stdout/stderr 保存后，编排 Python 把 Vite 的 `✓` 输出到 GBK 控制台时报 `UnicodeEncodeError`，当时 local 尚未启动。保留 `orchestration-resume.json`：企业不重跑，local 仅续跑一次并通过。该编排 traceback 只在工具返回中，未另行保存原始文件，本包不补造原始 stderr。

## 脱敏与可复核范围

原始本地文件未修改。公开文本以 `<WORKSPACE>`、`<WORKTREE>`、`<USER_HOME>`、`<SID>` 和必要凭据占位符去除私人定位信息，统一 UTF-8/LF；原始字节与公开字节 SHA256 分列 `provenance.json`。复制的原始结果元数据内历史日志摘要仍指原始文件，不能拿它比对公开脱敏日志。空 stdout/stderr 不重复提交零字节文件（类型检查主 stdout 保留），其字节数和摘要仍完整记录；构建后输入清单与构建前字节相同，保留一份公开内容并分别记录两份原始摘要。

`SHA256SUMS.txt` 覆盖本包所有其他文件。后验源码摘要和实现提交引用不证明当时工作树干净。本包尚未覆盖真实浏览器交互、WorkBuddy 原生用户/项目加载与优先级/缓存、三宿主完整旅程、最终 Go 全量及四目标构建、正式签名或外部验收；这些边界不能由本包开发检查替代。
