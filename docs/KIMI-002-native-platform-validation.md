# KIMI-002-NATIVE：真实平台能力与生命周期假设验证

## 1. 任务身份与范围

这是原任务书 M0 中 UX-001/UX-002 的接续，不是 KIMI-001 补修。K001 已合并结束。

```text
仓库：maoyadongsh/siq-agent-security
基线 main：1e20635843c0966e24d73d149e3d7bcd080f89c4
本批分支：codex/personal-k002-platform-readiness
实际执行候选：开始前读取该分支最新完整 SHA 并冻结；不要回退到本文件的 main 基线
```

用户已授权本批执行：在本分支追加必要的隔离验证脚本/测试、脱敏证据和交接，提交并推送以更新现有本批 PR。不得改 main、合并 PR、强推/变基重写历史、修改保护、发布、操作用户正在使用的 daemon/智能体或安装未经确认的软件。只对自己创建的隔离 profile/state/端口做进程操作。

先阅读根目录/模块/上级工作区实际适用的 AGENTS.md、原任务书、`docs/personal-experience-current.md`、`docs/personal-platform-validation-spec-v1.md`、ADR-049/050。原任务 D01–D11 不变；不把 CodeBuddy 当作 WorkBuddy，不把 Windows WSL 当原生 Windows。

## 2. 开工与基线保护

只读核对 git status、当前分支、origin 和远端 SHA。已有修改原样保留，不 git add -A，不清理未知 artifacts。干净且可快进时才同步；新建独立 worktree 优先。分叉时登记共同祖先和冲突范围，不自行重写带证据引用的提交。

审阅方已提交校验工具、QA schema、测试、跨 OS 工具 CI 与设计提案。先同步，不重复实现这些文件。审阅方交接后停止同组文件的并行写入；Kimi 成为本批验证增量的主写方。

固定代码候选 CANDIDATE（完整 SHA），编译到隔离目录并计算二进制 SHA-256。所有本次执行记录关联该候选；后续仅证据/文档回填提交另行记录。修改代码或测试脚本后，先提交新代码候选再重新验证相关项，不能把旧日志贴成新候选。

## 3. 本机与目标组合盘点

只收集测试所需的 OS 版本、CPU、运行方式、公开宿主版本/commit；不要导出主机名、用户名、个人路径、完整配置、环境变量、token 或密钥。不要执行从 Skill/配置读取出的命令。宿主二进制和源码入口必须由操作者实际确认。

使用候选目录内工具创建待测清单（目录自行选取新的私有隔离目录）：

```bash
python3 scripts/personal-experience/platform_acceptance.py init --candidate "$CANDIDATE" --out "$EVIDENCE_DIR/platform-matrix.json"
```

Windows 在对应 shell 中提供实际 SHA/目录；WSL 主 OS 记 Windows，guest_version 记录发行版与 WSL 内核的公开版本标签。工具不自动探测这些事实，null 不要用猜测值补齐。

18个组合是任务书建议架构的候选清单，不是支持承诺。不能访问的机器/桌面会话写 not_run 或 blocked/environment_unavailable；没有找到官方可用运行形态写 blocked/upstream_runtime_unconfirmed。不能据此删除用户目标或声称上游永远不支持。

## 4. 三平台分别核实八项能力

每个平台与每个实际 OS/架构/运行形态分别记录：

| 检查键 | 最低实际观察 |
| --- | --- |
| discovery | 隔离实例与合成 Skill 被发现，版本/实例分开；未读取私人内容 |
| normal_execution | 已授权合成调用通过真实宿主入口，产生预期隔离副作用 |
| pre_execution_denial | 越权动作到达门禁后拒绝，实际文件/受控接收端无该副作用 |
| service_unavailable_denial | 只停止测试 daemon 后 block 不放行；宿主自身超时另记 |
| approval_resume | 等待期间不执行、拒绝/超时不执行；允许后经过已有复核继续 |
| final_parameter_recheck | 批准后改变关键参数，最后可用执行检查点拒绝旧批准；没有该点就记缺口 |
| skill_attribution | 来源来自可核验宿主事件/受控上下文；自报名称不能取得其他 Skill 权限；未知保持未知 |
| install_interception | 原生安装入口是否可在实际写入/执行前进入 SIQ；只有事后发现则不记前置拦截通过 |

本机 OpenClaw/Hermes 复用 `scripts/personal-experience/` 的原生脚本及其 --help；先阅读脚本作用域与参数，再使用现有隔离测试方式。已核对的入口有 `hermes-cli-runtime-smoke.py`、`grant-resource-native-smoke.py`，安装后原生入口见本目录 README 的 `installed-skill-runtime-native-smoke.py`；OpenClaw 使用现有 README/源码所指的独立原生脚本。先核对帮助与参数，不猜测可执行文件路径。旧证据可用于定位，不替代新候选实跑。测试不用付费模型、真实联系人或真实外部修改；宿主没有确定性无付费执行路径时，明确阻塞，不擅自切换线上模型。

WorkBuddy 必须使用实际桌面应用名称/版本和受控桌面任务，不可用 CodeBuddy CLI 运行成功填它的行。官方资料核查起点：
- https://www.workbuddy.cn/docs/workbuddy/Overview （安装指南导航含 Windows/Mac）
- https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Plug-In （插件组成列出 Hooks，不能单凭此认定可用阻断合同）
- https://www.codebuddy.cn/docs/cli/hooks （仅用来对照 CodeBuddy Code，不能外推 WorkBuddy）

这些是2026-09-11检索线索，不是实机证据，也不确定最低系统/发行可用性。实际核查时记录精确页面与访问日期、产品版本及缺失信息。Linux/WSL 是否有目标 WorkBuddy 的真实运行形态须单列结论；网页/移动端不能擅自替代桌面目标。

## 5. 生命周期设计假设：只验证，不安装产品级后台项

对可用系统检查 ADR-050 的用户级机制是否存在、权限和路径是什么、登录/注销如何处理。比较 Windows 用户任务、macOS 用户 LaunchAgent、Linux 用户服务/桌面启动项；不修改正式启动配置，不把“命令存在”当成后台生命周期通过。

在测试账户或明确隔离环境有条件时，验证同一产品实例与错误服务端口区分、双启动/活跃锁不误删、关闭浏览器不退出服务、状态目录关联、优雅停止与重启。当前 `start-local.py` 只是开发入口；实际发现“同端口另一状态目录被复用”等问题要记录，不能猜已修复。

输出 `docs/k002-native-lifecycle-findings.md`：各系统可复用机制、权限范围、确认过与未确认的假设、下一步最小实现建议。无需批准新框架，不实现安装器/托盘/受控启动/原文存储/团队服务。重大范围取舍交审阅方，不替用户缩小目标。

## 6. 证据、校验与退出码

每项正/负向保留实际命令（脱敏）、退出码、宿主版本、候选 SHA、二进制摘要、实际观察与无副作用证明。执行命令不能含 token/个人绝对路径；截图和原日志先脱敏。先将可公开材料复制到新的私有 evidence 根，再填相对文件路径和真实 SHA-256。

不同平台/OS/运行方式不能复用同一份证据内容，工具将拒绝跨组合摘要借用。单个组合完整报告可供多个检查引用，但报告正文必须确有各项观察。工具只校验声明与字节一致，不验证正文真实性，禁止伪造或改标旧候选。

```bash
python3 scripts/personal-experience/platform_acceptance.py verify "$EVIDENCE_DIR/platform-matrix.json" --evidence-root "$EVIDENCE_DIR" --candidate "$CANDIDATE" --out "$EVIDENCE_DIR/verification-report.json"
```

普通退出0仅表示材料结构/摘要一致。另以新的输出文件运行 --require-native；未覆盖项应退出3，不当成工具故障修成0。无效输入退出2必须修复材料或工具并增加回归。输出文件存在时不覆盖；每次使用新文件名，保留失败记录。

## 7. 本批最低工程回归

```bash
python3 -m unittest discover -s scripts/personal-experience/tests -p test_platform_acceptance.py -v
apps/control-api/.venv/bin/ruff check scripts/personal-experience/platform_acceptance.py scripts/personal-experience/tests
apps/control-api/.venv/bin/python -m unittest discover -s scripts/personal-experience/tests -v
```

使用已有 `uv sync --dev --locked` 环境，不升级依赖。涉及实际代码增量的模块，按原任务书执行对应 Go/Web/合同/浏览器回归，不能只跑本工具测试代替。工作区最后检查 `git diff --check`、`git diff --stat`、`git status --short`。原有 ci/runtime-security/research/pages 与新 personal-experience 在最终 PR 候选实跑，nightly 跳过单列。

## 8. 交付与停止条件

交付路径建议：`docs/evidence/personal-experience/kimicode-k002-native-YYYYMMDD/`，以及 `docs/kimicode-k002-native-handoff.md`。报告实际候选/最终 HEAD、修改文件、逐项状态、实际版本、命令/退出码、摘要、CI、不能完成的具体环境和剩余产品决策。

达到 ready_for_review 的含义是本批可执行探测与材料已完成，**不是**所有目标原生通过；有环境或能力缺口时 UX-001/002 保持 doing/blocked。不得将本工具的合成单元测试填入原生矩阵。

在本分支提交并推送，更新已存在 K002 PR，不再创建重复 PR。无权限推送时准确记录本地 SHA，不改远端认证设置。完成本批即停止，不启动 UX-003 整套安装器、UX-010 自动更新、ADR-0048 或 LAN。后续由审阅方根据真实缺口确定下一批。
