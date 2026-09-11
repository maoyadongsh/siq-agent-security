# KIMI-001：个人体验接力开发——CI 基线恢复与回归修复任务书

## 1. 本批目标与执行方式

在保留 Codex 已完成的个人体验 M1–M34 增量的前提下，修复当前提交暴露的持续集成回归，建立可复验、可继续开发的基线。本批不是重做原任务书，也不是开始团队版；完成本批后停止扩展功能，交回代码、测试证据与交接报告，等待下一批任务。

执行者：Kimi Code。执行环境：用户本地仓库；原任务书记录的位置为 `/home/maoyd/siq/siq-agent-security`，必须先确认真实路径。审阅方：当前对话中的技术规划与代码审阅助手。

本任务书状态为“待执行”。以下失败信息来自已经读取的 GitHub Actions 记录和指定版本源码，不表示执行者已经在本地复现，也不表示已经确认全部根因。不得把本任务书直接登记为开发完成证据。

### 1.1 固定参考基线

```text
仓库：maoyadongsh/siq-agent-security
参考分支：main
参考 HEAD：b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8
父提交：a2f95c6fad1a04c776d57c4d4b9fd89b85c69b33
提交说明：agentshield: 个人体验周期 M1–M34 落盘
提交时间：2026-09-11T00:45:38Z（北京时间 2026-09-11 08:45:38）
建议工作分支：kimicode/personal-k001-baseline-repair
对应原任务：UX-000 的接力基线、UX-007 相关回归、AC12 兼容性及工程验证
```

M1–M34 是历史开发批次编号，不是原任务书 M0–M5 里程碑验收结果。本批使用独立编号 KIMI-001，不将其记成“个人阶段已经完成”。

### 1.2 用户工作区保护与提交权限

先检查当前分支、HEAD、暂存区、未提交内容与未跟踪文件。原任务书提到的 Vitest 未提交变更只是当时的状态；本批必须重新核对，不能假定它们仍未提交，也不能覆盖任何新遗留工作。

不得执行破坏性重置、清理、强推、自动合并、自动变基、删除活跃写锁、批量终止进程或更改用户服务配置。不得运行 `git reset --hard`、`git clean -fd`、`git add .` 或 `git add -A` 来省略文件审阅。不得打印完整环境变量、Git 凭据配置或密钥。

若 HEAD 已更新，先说明与参考基线的差异，检查这些问题是否已修复，再在实际基线上继续；不回退新工作来迎合旧任务。若其他人的未提交修改与本批重叠，先隔离和登记冲突，停止覆盖重叠部分；能安全独立推进的部分可以继续。不要把环境或凭据问题通过放宽权限来“解决”。

用户将本任务书交给执行者后，本批仅允许在专用分支对已审阅的本批文件形成清晰的本地提交。远端推送、创建/合并 PR、打标签、发布、修改仓库设置或重启正在使用的服务，仍须有用户明确授权；本任务书不包含这些权限。尚未推送时，报告为“本地已验证，远端 CI 待验证”，不得写成全部完成。

## 2. 开工前必须阅读的依据

先读根目录 `AGENTS.md` 及实际修改目录中的模块规则，尤其是 `apps/agentshield/AGENTS.md`。在现有模块内增量修改，不另建授权引擎或平行前后端。

必须对照以下现有文件，按真实目录核对路径：

- `docs/personal-experience-lan-team-development-taskbook-20260910-145507.md`：D01–D11、AC01–AC12、数据/权限/平台边界。
- `docs/personal-experience-development-progress-20260910.md`：当前状态表和 M33/M34 末尾的未完成项。
- `docs/personal-experience-requirements-baseline-20260910.md`、`docs/agentshield-dev-spec-v1.md` 及关联 ADR。
- `.github/workflows/ci.yml`、`.github/workflows/runtime-security.yml`、`.github/workflows/research.yml`：实际命令、工作目录、版本、条件和后续被跳过步骤。
- 下文列明的故障源码、测试、合同样例与依赖清单。

本批首先追加现状与修复设计记录。修复若涉及行为、合同或持久化语义，必须先解释现有合同与目标不变量，再同步规格/合同和代码。保持旧合同兼容；没有证据支持时，不改变既有授权规则。

## 3. 已确认的失败基线

以下记录均绑定参考 HEAD。执行时重新获取对应运行及最新重试结果，不能把旧失败或旧成功当成新提交结果。

| 编号 | 工作流 / job | 已观察到的失败 | 必须保留的解释边界 |
| --- | --- | --- | --- |
| K001-A | `ci`，run `34547879662`，job `103104306369`（agentshield） | 普通 Go 测试中，Grant 草稿并发请求出现 `409 grant_draft_unavailable`；`grant-draft-created.json` 合同样例不匹配 | 不是仅有格式问题；后续交叉编译、Skill 清单验证等步骤被跳过 |
| K001-B | `runtime-security`，run `34547879710`，job `103104306665`（runtime-security-toolchain） | 同样两项 Grant 草稿测试在 `go test -race ./...` 下失败 | 日志是测试断言失败，不能未经复现就称为 Go race detector 已检出数据竞争 |
| K001-C | 同一 runtime-security run，job `103104306477`（runtime-security-contracts） | Secure Agent 运行 100 个测试，记录 `failures=7, errors=20`；多个应用/服务用例在首次研究 `web_fetch` 被 `runtime_denied` 提前阻断 | 需查明授权、规则、资源匹配或测试设置的具体原因；不能通过放行所有动作修复 |
| K001-D | `research`，run `34547879675`，job `103104306293`（research-reproduction） | 研究脚本 10 个测试中 2 个 error，`dependency inventory does not match lockfile` | 台账检查、研究 metadata 检查及 lint 先前通过；失败点是后续打包测试，不应笼统说台账损坏 |

A/B 是两个运行环境中的同组症状，不代表已证明存在两个不同缺陷。C 的失败数是 unittest 汇总数，可能包含子测试，不能直接作为“27 个独立产品漏洞”。

当前同提交的 Web、Control API、Edge/Connector 等 CI job 有通过记录；不得因此宣称三系统原生平台验收完成，也不应将仓库笼统描述成全部不可用。

## 4. 唯一开发范围

### 4.1 K001-0：接力预检与失败复现记录

完成以下工作后再动产品代码：

1. 记录实际 HEAD、分支、工作区状态、适用规则、工具版本及已有修改归属。只记录必要的系统与工具版本，不收集用户资产、密钥或配置正文。
2. 建立本批交接文件 `docs/kimicode-k001-handoff.md`。将各失败登记为“待复现/已复现/已定位/已修复/已验证/阻塞”，附实际证据。
3. 在独立临时状态目录、测试 profile 和非用户服务端口运行测试。不连接用户真实联系人，不调用付费模型，不操作真实外部业务资源。
4. 按失败 job 原命令取得失败前证据。若当前环境不复现，不可直接跳过；比对工具链、CPU、工作目录、路径、时区、测试缓存和并发条件，保留差异。

历史 CI 中，普通 agentshield / Secure Agent 集成路径使用 Go 1.22.12；toolchain job 使用 Go 1.26.6，运行于 Linux amd64。它们是已观察到的基线版本，不是本任务建议的“当前最新版本”。对照实际工作流和模块支持约定复验，不擅自删掉任一现有测试版本。

### 4.2 K001-1：Grant 草稿幂等与合同样例回归

先读：

```text
apps/agentshield/internal/server/grant_draft.go
apps/agentshield/internal/server/grant_draft_test.go
apps/agentshield/internal/grant/draft.go
apps/agentshield/testdata/contracts/grant-draft-create.json
apps/agentshield/testdata/contracts/grant-draft-created.json
以及上述代码调用的 state 读写、CommitGrantFrom、revision/CAS、恢复逻辑
以及对应 packages/contracts 合同与 Python 校验
```

**并发问题。** 当前测试期望 8 个相同请求全部返回 200、引用同一草稿，只产生一次创建审计。检查现存草稿读取、签名校验、首次发布、冲突后读取和多文档提交可见性的顺序。将复现到的真实根因写清楚后，进行最小修复。

不得仅把测试期望改为“409 也算成功”，不得加任意 sleep 或无限重试掩盖竞争，不得移除签名检查、源修订检查、单写者、CAS 或审计。不同 source revision、actor、request ID 的请求不应被错误归并为同一请求；源授权变化、篡改或坏状态不能因幂等路径而得到放行。

修复后至少证明：相同并发请求返回同一草稿；只记录一次创建；源授权不变；草稿保持 `pending_approval`，不继承已批准/生效身份；草稿后续编辑后，原请求重试返回当前正确状态而非覆盖编辑；陈旧源、非管理凭据和损坏数据仍拒绝。新增必要的可控并发回归，不只依赖偶然调度。

**合同样例问题。** 对实际输出与 `grant-draft-created.json` 做逐字段差异分析，区分动态测试输入、环境差异与真实合同变更。现有测试只归一化生成时间和签名；这并不能证明其他字段必然稳定。

不得未分析便打开 `AGENTSHIELD_UPDATE_SAMPLES=1` 批量覆盖。若是夹具不确定，应固定输入；若是合理合同变化，应同步规格、合同及跨语言向量，并说明兼容性。不能通过删字段、放宽 schema 或不再校验签名来消除漂移。

### 4.3 K001-2：Secure Agent 正常链路与安全负向回归

先读应用/服务测试及相应初始化与调用链：

```text
apps/secure-agent/tests/test_application.py
apps/secure-agent/tests/test_service.py
apps/secure-agent/tests/test_siq_integration.py
apps/secure-agent/secure_agent/application.py
apps/secure-agent/secure_agent/skills.py
apps/secure-agent/secure_agent/gateway.py
以及测试实际调用的授权准备、SecurityClient、Go 决策和资源匹配实现
```

日志显示多个测试在读取仓库 `/commits/HEAD` 对应的首次 `web_fetch` 阶段收到 `runtime_denied`；正常任务与部分安全负向用例均未进入预期后续阶段。这是排查入口，不是已确认的具体算法缺陷。

取得本地测试的脱敏决策原因，追查实际 Grant、策略、主体/会话、资源约束及参数来源的匹配。判断是新实现回归，还是测试/演示准备逻辑未满足已确定的新合同；按证据修复正确层，不凭猜测扩大权限。

禁止：把 block 改成 warn/audit_only；把错误吞掉当成功；加入无界 `*` 授权；让模型持有管理凭据；将真实 SIQ 集成替换成“永远允许”的 mock；删除负向测试；将 expected verified 改为 failed 以通过测试。

至少成对验证：正常授权任务可完成其本地测试效果；同值不同来源的 MCP 负向仍拒绝；批准后撤销/参数替换仍拒绝实际副作用；fake-success 仍不被当成已核验；机密信息与不可信输入相关用例实际到达目标安全检查点；连续任务的授权、会话和效果不串用。

对于原本在初始化阶段提前失败的负向用例，报告中说明修复后是否到达其原定断言，不能只用“仍然失败”证明防护有效。

### 4.4 K001-3：当前依赖清单与研究打包回归

先读：

```text
scripts/research/package_source.py
scripts/research/test_package_source.py
scripts/research/test_verify_release_assets.py
scripts/research/check_metadata.py
scripts/check_research_task_ledger.py
docs/research/third-party-dependency-inventory.json
docs/research/third-party-source-inventory.json
THIRD_PARTY_NOTICES.md
LICENSES/README.md
以及清单实际引用的 lockfiles、license_files、源码/补丁摘要
```

`license_inventory()` 会比较清单里登记的锁文件摘要和当前实际文件。找出具体不一致的锁文件与依赖变化；可以优先检查本阶段已有的 Web/Vitest 变化，但不得未经比对就宣布根因。

按照仓库既有生成/审查流程更新**当前开发版本**的依赖清单、必要许可说明和来源记录。核对真实版本、直接/间接依赖、dev/runtime 分类及相关许可文件；不能只手工替换 hash 而跳过依赖差异。不得为了匹配旧清单而回退安全更新。

保持源码包校验严格：清单与锁文件不一致、缺许可文件、vendored 内容变化、路径逃逸、符号链接与资产替换等负向仍须拒绝。不得给比较条件加绕过或永久 skip。

不得重写研究预发布的 tag、归档包、历史签名/校验和、已冻结证据。当前清单变更必须登记为新开发版本的记录。若修复涉及真实许可选择、外部权利确认或改变产品范围，登记阻塞交回，不自行捏造许可结论。

### 4.5 K001-4：整体回归、可追溯交付与停止点

在同一候选代码身份上重跑相关完整回归。注意 GitHub 前一轮中因上游失败而 skipped 的步骤并未提供验证，修复后要执行适用后续步骤。

如出现与本批修复直接相关的后续失败，继续在本批做最小修复；若新问题需要扩大产品设计、改动大量独立模块或外部环境，记录新的阻塞和建议，不把它静默并入本批。不得为了保持小范围而把已经确认的失败写成通过。

完成代码和本地验证后，形成清晰的小提交、交接报告与证据索引。远端 CI 获得运行条件后，以对应新提交的实际结果补充报告。本批结束后停止，不自动开始 Hermes 新更新旅程、远端更新检查、可信 Skill 新协议、原文存储、安装器或 LAN 开发。

## 5. 修改边界

允许修改：上述直接相关的实现、测试、合同/样例、当前依赖清单和必要说明；既有开发台账的新增状态说明；本批交接报告与新证据目录。确有必要时可增加回归测试辅助代码。

工作流仅在有具体根因证明其配置有问题时做最小修复。不得删除失败 job、添加 `continue-on-error`、减少安全断言、缩小触发范围或修改 required checks 来制造绿色状态。不得顺便升级整套依赖、换框架、重排 UI 或重构整个 state 模块。

新证据建议位置：

```text
docs/evidence/personal-experience/kimicode-k001-<实际日期>/
```

其中 `<实际日期>` 在实施时替换；不得创建虚假的通过记录。大体积构建物/原始日志按仓库规则存于忽略目录或正式 CI artifact，不把用户数据和临时制品批量提交。

## 6. 验证命令与运行条件

下面是本批的最小本地命令集合。先读实际工作流，使用一致的工作目录和锁定依赖。每项独立保留退出码；管道收集日志必须保留被测命令失败状态，不得让最后一个 `tee` 掩盖失败。

### 6.1 只读基线

```bash
git status --short --branch
git rev-parse HEAD
git log -5 --oneline
git diff --stat
git diff --cached --stat
```

必要时在本机审阅实际 diff；不要把可能含敏感内容的全量 diff 未脱敏地放入公开报告。

### 6.2 Go 定向与全量验证

在 `apps/agentshield`：

```bash
gofmt -l .
go vet ./...
go test ./internal/server -run 'TestGrantDraft' -count=20
go test -race ./internal/server -run 'TestGrantDraft' -count=20
go test ./...
go test -race ./...
```

`gofmt -l .` 应无输出。合同/状态/授权模块有改动时补相应负向和跨语言验证。定向并发回归至少重复 20 轮；不宣称重复 20 轮就证明不存在所有竞争。

针对原 CI 的两个 Go 工具链运行适用测试，记录实际 Go 版本与架构。在 Linux arm64 本地通过不能代替 Linux amd64 CI。交叉构建、漏洞扫描、签名 Skill 清单验证及自扫描，使用 `ci.yml` / `runtime-security.yml` 原有命令和固定版本；不得覆盖用户正在运行的二进制。

### 6.3 Secure Agent 与研究验证

先在 `apps/control-api` 执行：

```bash
uv sync --dev --locked
```

再于仓库根目录执行（以下路径按该环境建立的虚拟环境）：

```bash
apps/control-api/.venv/bin/ruff check apps/secure-agent deploy/dgx-spark/preflight.py scripts/hackathon
PYTHONPATH=apps/secure-agent apps/control-api/.venv/bin/python -m unittest discover -s apps/secure-agent/tests -v
apps/control-api/.venv/bin/python -m unittest discover -s scripts/hackathon -p 'test_*.py' -v

python3 scripts/check_research_task_ledger.py
apps/control-api/.venv/bin/python scripts/research/check_metadata.py
apps/control-api/.venv/bin/ruff check scripts/research scripts/check_research_task_ledger.py
apps/control-api/.venv/bin/python -m unittest discover -s scripts/research -p 'test_*.py' -v
```

这些不是运行时/研究工作流的全部步骤。必须继续执行其中原定的 scenario contracts、Hermes 适配器回归、组件 benchmark、完整控制 corpus、研究浏览器与归档公共证据核验等**适用步骤**，以工作流内真实命令为准。需要额外本地宿主/浏览器/工具链而不可执行时标注缺口，不能改成通过。按事件条件本就不运行的 nightly 可如实保留条件性跳过，但上游失败造成的 skipped 不能当完成。

### 6.4 Web、合同与跨模块回归

在 `apps/web`：

```bash
npm ci
npm test
npm run build
npm run build:local
npm audit --audit-level=moderate
```

保持既有依赖锁定与合法许可证材料一致；漏洞检查发现新问题时分类记录，不在本批擅自整套升级或自动执行 `npm audit fix`。构建可能更新嵌入产物，遵循现有源码/制品规则，并审查是否确属本批必要改动。

在 `apps/control-api` 按影响范围执行：

```bash
uv run ruff check app
uv run pytest
```

修改共享合同必跑相应 Python/Go 对等验证；不以“本批主要改 Go”为由遗漏。控制面数据库验证使用隔离测试环境，不连接生产数据库。

提交前于仓库根目录执行：

```bash
git diff --check
git diff --stat
git status --short
```

另按仓库现有方式执行 secret 扫描/隐私检查；不得提交 token、私钥、原始用户内容或下载 URL 凭据。

## 7. 本批验收条件

| 验收编号 | 必须满足 |
| --- | --- |
| KAC-01 | 实际基线与工作区遗留已登记，没有覆盖无关修改，没有把历史未提交说明当作当前事实 |
| KAC-02 | 草稿相同并发请求在正常条件下全部成功且同一结果、一次创建审计；源授权不变，编辑后重试不覆盖，负向仍拒绝 |
| KAC-03 | 草稿合同样例差异已解释并消除；没有盲刷样例或放宽合同，跨语言验证通过 |
| KAC-04 | Secure Agent 全量应用/服务测试通过；正常路径完成真实隔离测试效果，负向到达预定检查点且无不应发生的副作用 |
| KAC-05 | 当前依赖清单与实际依赖一致；研究打包/资产验证正负向通过，历史发布证据未改写 |
| KAC-06 | 同一新候选上的 Go/Web/适用合同与工作流后续验证完成；不隐藏失败，不把 skipped 记成 passed |
| KAC-07 | 当前范围内实现、测试、规格/合同一致，生成物、源码、测试证据可关联，回退策略明确且不破坏状态/撤权 |
| KAC-08 | 远端对应提交的 ci、runtime-security、research 获得真实运行结果并通过适用门槛；原本通过的相关 job 无未解释回归 |
| KAC-09 | 交付文件无凭据/原文泄露，未降低 block、管理分权、来源校验、单写者、CAS、签名、历史不可变等安全边界 |

本地完成但尚无远端验证时，最多标记 `local_verified / awaiting_ci`；CI 尚失败或未执行不能标记本批 `done`。进入 `ready_for_review` 也不等于审阅已通过。只有回传证据、完成审阅后，才能决定下一批。

本批通过只表示接力基线恢复，不表示 UX-007、UX-010、UX-015 或个人版/团队版全部验收完成。

## 8. 中断恢复与交接格式

为避免额度或会话中断后丢失上下文，每完成一个独立修复或验证阶段，就更新 `docs/kimicode-k001-handoff.md`。不得依赖仅存在于聊天记录中的实施状态。

交接至少包含：

```text
任务：KIMI-001
状态：doing / blocked / local_verified / awaiting_ci / ready_for_review
实际基线 SHA：
当前分支：
本批提交 SHA（最终提交后在回复中补充）：
初始未提交/未跟踪内容与归属：
实际改动文件及每项理由：

问题 A/B：复现条件、真实根因、最小修复、安全语义是否改变
问题 C：复现条件、真实根因、正常与负向具体到达的检查点
问题 D：不一致的具体锁文件/依赖、清单变更及历史证据保护

测试：逐项命令、工作目录、工具版本、OS/架构、退出码、实际结果、证据路径
CI：提交 SHA、workflow/run/job、状态、链接、未运行/失败原因
未验证边界与外部阻塞：
恢复/回退：不得重置用户数据或复活撤销权限
继续所需的下一个最小动作：
本批是否越界：
```

建议提供机器可读 `verification.json`，字段包括参考基线、被测代码身份、各命令/退出码、各证据摘要、CI run/job 引用及未验证项。不要在提交中的文件要求写入该文件所属“最终提交 SHA”而制造自引用；可记录已测试代码提交/树身份与必要工作区 diff 摘要，最终交付 SHA 在提交完成后的回复中给出。

无法完成的测试留为 `not_run` 或 `blocked` 并解释；仅有交叉构建或 synthetic fixture 时明确标注。日志和证据使用脱敏合成数据，不复制用户的完整 runtime 状态目录。

## 9. 退出与下一批边界

本批最终回复必须说明：修复了什么、尚未修复什么、实际测试结果、提交身份、能否进入审阅。不要只回复“开发完成”。

本批不执行新的 Hermes 更新全旅程。该方向是候选下一批：真实宿主中的更新、旧会话撤权、新版显式授权启用，以及相应恢复证据。是否发出下一批任务由本批审阅结果决定；本地与 CI 基线未恢复时，只返回本批补修，不继续堆功能。

## 10. 可追溯依据

以下链接是本批现状依据，访问时请保持 SHA 和 run/job 身份，不替换成浮动 main 后冒认同一证据。

- 参考提交：https://github.com/maoyadongsh/siq-agent-security/commit/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8
- 开发台账：https://github.com/maoyadongsh/siq-agent-security/blob/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8/docs/personal-experience-development-progress-20260910.md
- ci / agentshield：https://github.com/maoyadongsh/siq-agent-security/actions/runs/34547879662/job/103104306369
- runtime-security / contracts：https://github.com/maoyadongsh/siq-agent-security/actions/runs/34547879710/job/103104306477
- runtime-security / toolchain：https://github.com/maoyadongsh/siq-agent-security/actions/runs/34547879710/job/103104306665
- research / reproduction：https://github.com/maoyadongsh/siq-agent-security/actions/runs/34547879675/job/103104306293
- 草稿测试：https://github.com/maoyadongsh/siq-agent-security/blob/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8/apps/agentshield/internal/server/grant_draft_test.go
- 草稿接口：https://github.com/maoyadongsh/siq-agent-security/blob/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8/apps/agentshield/internal/server/grant_draft.go
- 打包校验：https://github.com/maoyadongsh/siq-agent-security/blob/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8/scripts/research/package_source.py
- M34 浏览器证据：https://github.com/maoyadongsh/siq-agent-security/blob/b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8/docs/evidence/personal-experience/skill-update-ui-20260911/browser/result.json

以上历史通过、失败和未验证状态分别保留。本批任务的要求与建议不是既有实现事实。
