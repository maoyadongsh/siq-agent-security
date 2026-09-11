# KIMI-001-R1：剩余安全测试语义修复与最终验收

## 1. 执行目标和授权边界

这是 KIMI-001 的补修，不是 KIMI-002，不开启新的 Hermes 更新、自动更新检查、隐私原文存储或 LAN 功能。

用户已授权在现有仓库继续补修；本任务交予 Kimi 后，只在下述专用分支形成增量提交并推送，以更新既有 PR #27。不得直接修改 main、合并 PR、强推、变基重写既有历史、修改保护/工作流门槛、发布或重启用户正在使用的服务。不要再建重复 PR。当前补修代码交接给 Kimi 主写，审阅方不同时改同一组文件。

```text
仓库：maoyadongsh/siq-agent-security
分支：kimicode/personal-k001-baseline-repair
PR：#27（保持草稿）
原 Kimi 交付 HEAD：8b53ddff0463efed2fe56d62954d382f3dbb163e
审阅方已推送代码提交：90bd14ed7a1aa812107bde2826f94da605ee3901
代码 tree：e3c7bfe4a6905eb7138af39f6edbfd2281d58d3e
```

本任务书可能由后续测试/文档提交加入同分支。开始时重新确认远端 HEAD；保留所有新改动，不回退到上述旧 SHA。旧任务书和原交接记录是历史依据；最新 R1 状态见 `docs/k001-r1-review-handoff.md` 和 PR 讨论。

先读取根目录和模块 `AGENTS.md`、用户本机上实际适用的上级工作区规则、原个人任务书、KIMI-001 任务书、现有规格和相关 ADR。原个人范围 D01–D11 不变，遵守先个人后团队。

## 2. 已由审阅方完成，不得重复或覆盖

### 2.1 内嵌适配器同步

`apps/agentshield/internal/adapterinstall/assets/hermes/__init__.py` 已与 `adapters/runtime/hermes-agentshield/__init__.py` 使用同一 Git blob `581932d05dfdfac84b605259f89f66985b81677e`。保留原逐字节一致性测试。

### 2.2 文件创建前校验

`SecureApplication.run` 入口在分配 run ID、写目录/文件、准备 Grant 和调用模型/网络之前校验 `confidential_name`。当前仅支持 `.env` 和 `confidential-note.txt` 两个既有操作者夹具名。保持下游 TaskAuthority/工具层路径及内容校验，不将此参数开放给模型或 HTTP 请求。

新增 `apps/secure-agent/tests/test_confidential_preflight.py` 两个测试方法：52 个非法输入子用例、4 个支持名称子用例。测试设有旧代码副作用 tripwire，重跑旧实现不会实际写越界文件。

审阅环境仅完成原文件 Git blob 一致性核对、Python 语法检查和抽取入口方法的隔离检查；未取得完整 clone，未在该环境运行完整应用/Go/真实平台验证。52+4 子用例不是“56 项真实平台测试”。实际新增模块导入与全量结果须看对应候选 CI。

## 3. 先同步并核对本地工作区

使用只读命令记录：

```bash
git status --short --branch
git rev-parse HEAD
git log -8 --oneline
git diff --stat
git diff --cached --stat
```

核对未提交、未跟踪内容和归属。只有工作区干净、已在目标分支且能快进时，才执行 fetch 和 `git merge --ff-only origin/kimicode/personal-k001-baseline-repair`；不是把功能分支合并到 main。不使用 `reset --hard`、`clean -fd`、`git add .`、`git add -A`。遇分叉或重叠修改，先登记并隔离，不覆盖。

本机父目录规则、当前进程和真实服务状态不能从远端推定；只使用自建临时状态目录、隔离 profile 和非用户服务端口。禁止真实联系人、真实凭据内容或付费模型调用。

## 4. 本批剩余工作

### R1-A：拆开凭据拒绝和成功读取机密后的安全场景（合并阻塞）

目前 `secure_agent/skills.py` 在 `SkillRunner.research` 捕获 `Blocked` 后，用 `denied.reason.startswith("credential path ")` 决定继续；原 trifecta 测试第一步从 allow/materialized 改成 deny/not-materialized。该历史结果可以证明一次凭据访问尝试被拒，但不能代替成功读取后的信息流验证。

先在本机真实隔离 daemon 复现，读取以下实际实现与相关测试：

```text
apps/secure-agent/secure_agent/{application,authority,gateway,skills,security,tools,confidential}.py
apps/secure-agent/tests/{test_application,test_gateway,test_siq_integration,test_service,test_confidential_preflight}.py
apps/agentshield/internal/receipt/ 中 Decide、Observe、污点累积及恢复实现
apps/agentshield/internal/runtimeaction/ 与 trustedcontext/ 的现有支持范围
scripts/research/browser_fixture.py 及其实际断言
当前 Secure Agent README/演示说明与相关 ADR
```

分别交付以下三类证据，不能用同一个更名测试冒充全部：

1. **凭据硬拒绝**：`.env` 读取被 Go 边界拒绝；执行器没有进入、没有 Observe 伪报读取成功；正常 SkillRunner 停止依赖该读取的后续步骤。新增其他原因的 Blocked/无效授权拒绝仍终止的负向。正常执行路径不得依靠人类可读 reason 字符串作继续依据，也不得伪造读取结果。
2. **真实允许读取的非凭据合成数据场景**：从 `confidential-note.txt` 等既有受控夹具通过真实 ToolAdapters 成功读取，固定字节校验和来源必须真实。核对现有引擎如何将其识别为私有数据，后续如何结合不可信输入和外发边界；原定检查点必须可达。不得只把文件叫 confidential 就声称引擎已识别；不得由模型/测试直接改私有内存标志、伪造 Observe、放宽凭据规则或跳过 Gateway。
3. **拒绝尝试后的保守状态**：若要保留这种引擎行为的测试，在独立引擎/集成用例里显式再次提交请求，准确命名为拒绝尝试后的状态保留；不为推动演示而在通用 SkillRunner 吞掉拒绝，也不说私有文件已读取。

先写简短修复设计和测试语义对照，再改代码。允许调整隔离合成夹具和当前演示文字，但保留正常、副作用核验、MCP 同值来源、批准后撤销、参数替换、fake-success 及文件篡改/符号链接负向。

**重要限制**：如果真实代码没有“受信任的非凭据私有文件分类”入口，明确列出可见证据和最小缺口；先完成能独立完成的 fail-closed 修复和诚实场景分离，并把真正私有读取场景登记为设计阻塞。不得为交付而新造一套 Authority、泛化污点算法或无界授权。确需新合同/引擎能力时提交最小 ADR/合同设计给审阅方，而非在本批静默扩大实现。未解决的原需求不能计为通过。

同步检查 `gateway.Blocked.reason` 是否仍需保留；不把原始错误文本、路径或合成内容无界写入默认日志。更新当前浏览器/应用的标题和预期，不能只因为被拦截就断言到达了 lethal_trifecta。

### R1-B：确定性证明在途草稿提交等待（KAC-02 证据补足）

当前 `TestGrantDraftHTTPTornCommitRefusedThenSettled` 手工造撕裂文件，再补 done 标记，验证了坏状态拒绝和既有记录重用；它本身不证明一个活跃提交持有锁时，第二个相同 HTTP 请求经过此次修复后等待并成功。

复用既有仅测试故障注入机制，增加可控并发正向：在 grant 发布、done 未发布的窗口暂停真实写者；发出第二个同请求；解除窗口后两个请求都指向同一已完成草稿，状态正确，创建审计只有一次。保留源 revision/CAS、签名、操作者/请求隔离和崩溃撕裂拒绝。

不使用任意 sleep、无限重试或删断言。确定性用例应能证明暂时恢复原 handler 对 ErrIncompleteCommit 直接 409 的逻辑时测试失败，再恢复修复后通过；这种变异检查在隔离 worktree 内完成，不提交回退代码。不得为了测试向生产 API 暴露故障注入开关。

### R1-C：最终候选全量复验和证据清理

以最终干净代码候选复验，而不是汇总不同中间状态的绿色日志。必须检查两个适配器文件逐字节一致；任何后续适配器修改同步内嵌副本。

```bash
# 仓库根目录
cmp adapters/runtime/hermes-agentshield/__init__.py \
  apps/agentshield/internal/adapterinstall/assets/hermes/__init__.py

# apps/agentshield，按工作流要求使用 Go 版本
# count=1 明确禁用结果缓存；gofmt 输出须为空。
gofmt -l .
go vet ./...
go test -count=1 ./...
go test -race -count=1 ./...
go test -race ./internal/server -run TestGrantDraft -count=20

# 仓库根目录，先在 apps/control-api 建立 uv --locked 环境
PYTHONPATH=apps/secure-agent apps/control-api/.venv/bin/python -m unittest discover -s apps/secure-agent/tests -v
apps/control-api/.venv/bin/ruff check apps/secure-agent adapters/runtime/hermes-agentshield
apps/control-api/.venv/bin/pytest adapters/runtime/hermes-agentshield/tests/ -q
```

继续运行原 KIMI-001 任务书和三条工作流的适用完整后续步骤：合同/语料/benchmark、研究浏览器、Web 及嵌入构建、四目标编译、清单验签、自扫描、secret 扫描。不要将上游失败后的 skipped 记成通过；按事件本就不运行的 nightly 单独登记。

提交和推送仅本批审阅过的文件至原分支，PR 将重新触发 CI。记录新提交 SHA、测试合并候选 SHA、run/attempt/job 和结果；不要借用旧候选绿灯。CI 门槛由实际仓库配置决定，不凭聊天中的检查数量推定。

机器可读证据使用真实命令和数值退出码，不写 `post-commit` 等占位为通过；补充源码身份、二进制摘要、日志摘要和范围。测试结果在代码提交后形成，可用后续文档提交引用先前被测代码，不制造“文件包含自身最终提交 SHA”的循环。

原 `verification.json`、旧失败日志保留为历史。更正“全部已先复现”的概括：并发故障原交接说明是本机未自然复现、根据 CI 和源码定位，不应篡改为已自然复现。旧本地全绿不能自动证明最后一次适配器修改后的候选全绿。

## 5. 完成条件与停止点

- 已有两项直接修复保持有效；新增测试在真实模块导入与 CI 下执行。
- R1-A 各类测试语义、实际工具执行/观察和界面说明一致；不再以错误文本控制正常执行。无法完成的原定分类能力明确设计阻塞，不能标 done。
- R1-B 活跃并发窗口正向和崩溃撕裂负向有各自证据。
- 最终候选 ci / runtime-security / research 适用 job 通过，尚未执行者登记 pending/not_run；无降低门槛和签名/撤销/来源约束。
- 新交接文件准确引用提交、实际命令/退出码、日志与未验证边界；没有真实用户内容、凭据或私钥。
- 不合并、不转为已批准、不发布、不开启下一批功能。

完成回复格式：

```text
任务：KIMI-001-R1
状态：blocked / ready_for_review（CI 通过不等于审阅通过）
实际基线和最终分支 HEAD：
新增提交和逐文件目的：
R1-A：三类场景实际语义、代码修复、尚需设计项
R1-B：确定性并发正向及变异检查、撕裂负向
R1-C：最终候选测试、CI run/attempt/job、未验证范围
证据和交接文件：
是否推送：
main/发布/用户服务：未修改
```

本批回退用经审阅的 revert/修复提交，不重置用户工作区，不复活撤销的运行权限。若额度不足，每完成一项就更新交接和最小安全提交；停止时说明精确位置，不依赖聊天记忆。
