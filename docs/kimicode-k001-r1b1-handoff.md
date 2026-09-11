# KIMI-001-R1-B1 交接：HTTP 在途草稿回归固化

```text
任务：KIMI-001-R1-B1
状态：ready_for_review（CI 通过不等于审阅通过）
实际基线：47a9809e62f2d03765a6ba7a7aeebe9028c98a69（工作区核对干净后开工，无他人改动被覆盖）
被测代码候选：e4454346430fe771d644595a473e3b633e770479（代码/测试/脚本冻结点）
最终分支 HEAD：本交接 docs 提交（仅文档；SHA 在最终回复与 PR 中给出）
```

## 新增提交与逐文件目的

- `4ad9773` agentshield：HTTP 门控回归与变异复跑入口
  - `apps/agentshield/internal/server/grant_draft_inflight_test.go`：新测试（下述）
  - `apps/agentshield/internal/state/commit.go`：`SetCommitBoundaryHook` 导出测试桥接
  - `scripts/personal-experience/grant-draft-inflight-mutation.py`：版本化变异复跑入口
  - `scripts/personal-experience/README.md`：登记运行方式与边界
- `49a8bf7` agent：README/DemoPage 文案收窄为「执行会话的依赖步骤」，内嵌产物重建（§6）
- `e445434` agentshield：变异脚本 lint 修正（可执行位、导入序、显式 check=False）

## 测试辅助跨包设计说明（任务书 4.1 要求）

`commitBoundary` 是 state 包既有的仅测试故障注入变量。HTTP handler 测试位于 server 包，Go 无跨包测试可见性，因此新增 `state.SetCommitBoundaryHook` 导出函数作为最小桥接：它只替换进程内阶段观察回调，不可经 HTTP/CLI/环境配置到达，不引入 unsafe/linkname，不改变任何提交协议与校验，生产二进制不安装观察者（零值即 no-op）。server 测试通过它把真实写者暂停在「grant 已发布、done 未发布」的窗口，驱动的是真实 handler、真实 Store 与真实文件发布，未复制简化 handler，无 mock 伪成功，未伪造 ErrIncompleteCommit。

## 测试如何满足任务书逐条要求

- 第一个请求经实际 HTTP route（httptest + 真实 mux/鉴权链，与既有 server 测试同一设施）创建真实签名源授权后的草稿。
- 写者由事件/通道暂停在真实窗口；测试自身在窗口内读到 `ErrIncompleteCommit`（非仅启动 goroutine 后定时推定）。
- 第二请求在窗口保持期间未返回即证明其已进入本次修复的等待路径（窗口内读到 ErrIncompleteCommit 后唯一驻留点是 commit 锁）；旧 handler 在此必然窗口内返回 409，构成确定性变异信号。
- 释放后两请求均 200、同一 grant_id、reused 语义分别为 false/true；草稿 pending_approval 且签名有效；`grant_draft` 审计恰一条；源文档字节与 revision 不变。
- 既有撕裂负向、编辑后重试、陈旧源、非管理凭据测试原样保留并通过。
- 测试自然进入 `go test ./...` 与现有 CI 正常回归路径；变异检查走版本化脚本（非 CI 门禁，README 登记）。
- 清理：全部接收有 30s 有界失败出口；失败路径释放写者、回收 goroutine，且在确认无提交使用后恢复全局钩子。

## 变异与正常结果（数值）

见 `docs/evidence/personal-experience/kimicode-k001-r1b1-20260911/mutation-result.json`：变异体 `go test ... -count=2 -v` exit=1，失败签名 `duplicate returned inside the window instead of waiting: 409`（预期 409 幂等断言，非编译失败/超时/panic）；恢复后 exit=0，`--- PASS`。执行环境 go1.26.5 linux/arm64，HEAD e445434。

## 本地验证矩阵

逐项命令/退出码见同目录 `verification.json`：gofmt/vet、`go test -count=1 ./...`（33 包）、`-race -count=1 ./...`（33 包）、新测试 ×20 及 -race ×20、`TestGrantDraft` -race ×20、go1.22.12 定向、secure-agent 104 项、ruff（含新脚本）、web 测试+双构建、四目标交叉编译、manifest-verify、自扫描 admit_with_conditions、hackathon 语料、浏览器九场景。

## 远端 CI（推送后回填，不借用 47a9809 绿灯）

- 待推送后填写 run/job。

## 未验证边界

- 本机 arm64；amd64 由 CI 覆盖。
- control-api 全量 pytest/alembic、runtime-security 基准、edge 矩阵：本批未改其代码面，以远端 CI 为准。

## 范围确认

未重做 R1-A；未实现 ADR-0048（保持提案/未实现，方向 3 未被当作需求放弃）；保留 Hermes 内嵌同步与文件名前置校验；未合并 main、未强推、未改保护规则、未发布、未操作用户服务。
