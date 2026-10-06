# Skill 更新后的旧会话冲突分类修复

日期：2026-10-06。来源：DGX Spark / Hermes / OpenShell / Research 真实权限测评。

## 触发及原行为

一个已登记的 Runtime Identity 会话绑定旧 Skill Grant。通过公开更新 API 替换 Skill 后，旧 Grant 被撤销；管理端终止旧身份、激活新版，再为同实例创建新身份。新身份尝试登记旧 session 时没有获得权限，但原 API 返回 `503/runtime_identity_unavailable`。

准备批次 `research-permissions-skill-replacement-002` 保存了准确应答。HTTP 回归测试 `TestRuntimeSessionReplacementWithRevokedGrantReportsConflict` 在修复前重现同一 503。本项属于错误分类缺陷，不能描述成已发生的越权漏洞。

## 修正

`runtimeidentity.EnrollContext` 解析失败时，如果已返回验签成功的历史 Binding、平台/Agent/session 完整匹配，并且绑定的 Intent/task 与当前身份派生值不同，则返回既有授权冲突，HTTP 为 `409/runtime_identity_authority_conflict`。

没有验证成功的历史 Binding 时仍按不可用拒绝。不会覆盖历史绑定、续期、恢复旧 Grant 或自动批准新版。新身份需使用新的 session。

## 验证与制品

- 新增 HTTP 回归：修复前失败；修复后旧会话重复登记均 409，旧凭据仍 401，历史 Binding/Grant 引用不变，新 session 正常 200。
- `go vet ./...` 与 `go test ./...` 通过。
- Python `app/tests/test_schema_contracts.py` 通过。
- Linux arm64/amd64、macOS arm64、Windows amd64 交叉编译通过。交叉编译不代表后两者实机验收。
- 修改的 Go 文件已格式化；全仓检查发现四个此前未格式化的无关文件，未代为重写。

新 Linux arm64 制品 SHA-256：`68e7f95cb2e54e86943bfe2c3ee635f103e2c91fcfcc275b8994e0b8b4691796`。制品来自当前工作树，包含原有未提交修改；来源在新批协议中冻结，不声称与旧二进制只有此一处差别。

真实业务复测另用 `research-permissions-skill-replacement-003`；最终状态以其报告和独立核验为准。本修复没有替换日常运行服务，也没有发布或提交。
