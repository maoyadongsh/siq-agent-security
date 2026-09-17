# R01（N05）接续实现独立复核记录

- 复核时间：2026-09-14T18:50:32+08:00
- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- 分支：`kimi/personal-v4-r01-20260914`
- 基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`（与复核时 `origin/main` 的 merge-base 一致）
- 状态：代码和证据已落盘，尚未提交、推送、合并或发布

## 1. 接续复核发现与修复

Kimi 留下的首轮实现因离线 CLI 使用恒定返回 `ErrChanged` 的 Skill target resolver，真实装配无法签发
SEC，活体验证停在 `skill_context_session_unbound`。接续实现改为从隔离的 Hermes home 解析真实安装目标，
随后补齐以下安全边界：

1. 所有 `skill-context` CLI 命令取得状态单写者锁并恢复未完成的 Grant 提交；daemon 持锁时 CLI
   明确失败且不写入 SEC 文件。
2. SEC 有效期不得超过签名 session binding 有效期；每次使用重新校验 runtime identity、平台、
   Agent、固定 Grant、session binding、安装内容和撤销状态。
3. 同一 session 禁止 session 级 SEC 与任何 task 级 SEC 重叠；不同 task 的受控上下文可以并存。
4. import 保留范围的已安装 Skill Grant 无条件要求 verified SEC，旧配置开关关闭也不能用复制 claim
   获得 Skill 专属放行。
5. runtime identity 按实例查询时跳过已撤销前身，继续寻找有效替代身份。
6. verified 回执必须含服务端计算的 `call_binding`；mismatch/unknown 回执不得携带该字段。
7. 随机 ID 生成失败改为返回错误，避免进程 panic。

## 2. 验收结果

本地服务级活体共 57 步全部通过，详见
[活体验证报告](r01-skill-context-20260914/report.md)。验证使用真实候选二进制、真实 HTTP 服务、
签名状态和隔离 HOME/HERMES_HOME，覆盖正确归属、无 SEC、跨会话、跨任务、claim 切换、安装
内容变化、SEC 撤销、Grant 撤销、writer lock 与回执链。证据目录共 102 个文件，其中
`sha256.txt` 覆盖其余 101 个文件并已逐项复核。

复核命令和结果：

| 范围 | 命令摘要 | 结果 |
| --- | --- | --- |
| Go 静态检查与全仓测试 | `go vet ./...`、`go test ./...` | pass |
| 关键状态并发检查 | `go test -race` 覆盖 skillcontext/receipt/state/skillinstall/runtimeidentity/server | pass |
| Python 合同与服务回归 | Control API 全量 `pytest -q`；Hermes adapter pytest/Ruff/镜像一致性 | pass；adapter 58 项 |
| Web | Vitest；企业版与本地版构建 | pass，24 文件/90 项 |
| 证据完整性 | 精确凭据模式扫描；`sha256sum -c sha256.txt` | 无泄漏匹配；101/101 pass |
| 格式 | `git diff --check` | pass |

R02 整合后重新构建同一工作树候选并重跑本节 57 步活体，仍为 57/57 pass；以下交叉构建摘要也来自
整合后的最终源码。Control API 全量回归只有既有的 Starlette/httpx 弃用警告。

四平台无 CGO 交叉构建：

| 目标 | SHA-256 |
| --- | --- |
| linux/amd64 | `fd6e4a32d1cb5074b233cd56bcf20cbbe4aa3097d1e9b1be15c430abbc29ad88` |
| linux/arm64 | `ea8624c4c33094deca7197bf92901a246ea4484a31b45e276fe4370a681670c6` |
| darwin/arm64 | `82e568ab9464dafd35b4543b51a3b1abb5df19d4022c67c45f4e643821857276` |
| windows/amd64 | `4ce84d991a8ab9583a78f671bad1e4f5ccc5f1724040491181f940c5943a4a2f` |

这些哈希只证明当前源码可交叉构建，不替代 Windows/macOS 签名发行或实机验收。

## 3. 结论和剩余边界

R01 的安全组件、合同、前端证据展示和 Linux/Hermes 本地服务级活体达到阶段性交付要求。
状态保持 **partial**：本批以与适配器相同的 HTTP 请求执行活体验证，没有启动计费模型，也没有在
Hermes 原生插件进程中完成真实工具调用。OpenClaw 会话级接入、同一 Agent 下两个真实 Skill 的
宿主级权限隔离，以及 Windows/macOS/WorkBuddy 原生材料仍待对应平台批次。不得据此关闭 N05、
N09 或开始 T01–T06。
