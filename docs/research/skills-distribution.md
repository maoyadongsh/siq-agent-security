# SIQ Skill 与 vercel-labs/skills 的分发兼容

本轮把 `skills` 作为可选分发工具，提供固定版本、内容一致性检查和安装/卸载验证。SIQ 的静态准入、人工授权和运行时裁决仍由现有二进制与适配器负责。

这是独立的分发验证，不改变 V5 源码身份、制品、视频或实验分母，不提升任何平台的保护等级。

## 使用已固定的验证工具

运行环境：Linux 或 macOS，Python 3.12+、Node.js 24+、Git。下载阶段需要访问官方 npm registry；不使用本机 npm mirror 配置，不执行 `npm install` 或任何 lifecycle。上游 CLI 与全部运行依赖的精确版本、SHA-512 integrity 和 SHA-256 见 [skills-upstream.json](../../scripts/research/skills-upstream.json)。当前基线为 `skills@1.5.26`，Git commit `d667282815248da03a08a18272b5d2eef9caf77c`。

先运行不访问网络的负向测试：

```bash
python3 -m unittest discover -s scripts/research -p 'test_*distribution*.py' -v
```

从仓库根目录运行真实 CLI 验证，每次使用新的输出目录：

```bash
python3 scripts/research/skills_distribution_smoke.py \
  --out-dir .tmp/skills-compat/my-first-run
```

工具从 **当前 HEAD 的 Git archive** 取得 `skills/siq-agent-security`，因此不包含尚未提交的 Skill 修改。记录中的 `source.commit` 是被分发的源码身份；`runner_sha256` 则标识本次验证工具。修改测试工具不要求改写发布身份。

执行步骤是：校验固定 npm 包 → 安全提取普通文件 → 导出明确 commit 的 SIQ Skill → `--list` → 四个平台逐一 `--copy` 安装 → 比较完整文件集合、摘要、字节数与 POSIX 可执行位 → 卸载 → 核对安装目录与项目 lock 条目均已清除。同目录下另设一个无关 Skill 及 lock 条目，核对它们保留原样。源文件再次读回，确认测试没有改动候选内容。

| Agent 目标 | 上游标识 | 临时项目中的目标目录 |
| --- | --- | --- |
| OpenClaw | `openclaw` | `skills/siq-agent-security` |
| Hermes Agent | `hermes-agent` | `.hermes/skills/siq-agent-security` |
| CodeBuddy | `codebuddy` | `.codebuddy/skills/siq-agent-security` |
| Trae | `trae` | `.trae/skills/siq-agent-security` |

报告保存在输出目录的 `result.json`，整体 `result=passed` 才算本轮通过。失败尝试也保留报告；不要覆盖或删除失败记录来呈现全绿。上游普通文本模式可能在单项失败时返回 0，所以工具同时验证 add 的 JSON、实际目录、完整文件内容以及 remove 后的 lock，而不是只看退出码。

## 测试隔离与证明范围

测试会运行已经固定并校验的上游 CLI；**不运行任何 SIQ Skill 的 bootstrap、adapter、eval fixture 或其他候选脚本**。不会启用真实 Agent，也不会签发 Grant。

- `os.homedir()` 通过测试专用 preload 指向临时目录；不修改 `HOME`、`CODEX_HOME` 或用户配置。临时 home 内预建空的 `.codex`、`.zcode`、`.minimax`，用于短路上游卸载时的系统级 Agent 探测。这些标记不证明相关 Agent 已安装。
- 子进程环境不继承 token、`NODE_OPTIONS`、代理凭据或用户命令搜索路径，关闭 telemetry；Node permission 限制写入为本次临时目录，并禁止子进程。
- Node 的 `fs.cp` 会读取目标祖先的元数据，因此 Node 只读许可为 Linux 的 `/tmp` 或 macOS 的 `/private`，**读取范围比本次临时目录宽**。真实 home 读取、越界写入与子进程启动均在运行 CLI 前执行负向探针；任意探针未按预期拒绝则本轮失败。
- Node permission 不在此处提供已验证的网络隔离；报告固定记录 `network_isolation_verified=false`。这套试验不是用于运行任意恶意程序的安全沙箱，也不提供同 UID 对手的零竞态保证。
- 四个 Agent 的目录投递成功不代表四个原生 Agent 已运行，也不代表 L1/L2/L3 强制执行已成立。此工具只测试 project / copy / local source，不覆盖 global、默认 symlink、`skills update`、`skills use` 或 Windows CLI 主机。

## 单独核对安装内容

对两个静态目录可以只运行比较器，不下载或运行上游：

```bash
python3 scripts/research/verify_skill_distribution.py \
  --source /absolute/path/to/reviewed-siq-skill \
  --installed /absolute/path/to/installed-siq-skill \
  --out /absolute/path/to/new-distribution-report.json
```

退出码：0 表示一致，1 表示内容差异或输入树被拒绝，2 表示输出路径或写入错误。输出文件必须不存在且位于两个输入树之外。工具只写新报告。

比较器拒绝 symlink（包括输入根）、FIFO 等非普通文件、控制字符路径、读取期间检测到的变化和超预算的树。默认最多 2,048 个文件、32 MiB 总内容、16 层路径；目录和文件合计还有 4,096 个遍历项上限。空目录不参与内容摘要。该策略专用于本轮 copy 分发验证，不改变 SIQ admission 对根入口别名或根内普通文件链接的既有语义。

报告 `tree_sha256` 是比较器对完整文件元数据列表的确定性摘要，包含可执行位，**不是** SIQ admission 的 `content_hash`，也不是上游 `computedHash`。报告不验证签名是否可信；即便两个目录中的 manifest 相同，也只能证明 manifest 字节未改变。安全结论必须另行使用可信二进制。

## 安装入口与独立使用条件

仅将 `siq-agent-security` 作为本轮分发对象。`secure-research`、`secure-report`、`secure-delivery` 依赖 `apps/secure-agent` 的内置 `SkillRunner` 与应用合同；不要用 `--all` 将它们宣传成无需应用环境的独立 Skill，也不要用 `--full-depth` 将恶意测试 fixture 当作发布入口。

1. 先按[研究发布验证说明](release-authentication.md)核对来源与签名。当前研究版是源码预发布，没有新编译二进制；从源码构建时遵循[复现指南](../../REPRODUCIBILITY.md)。不要因为 `skills add` 成功就假定二进制已准备好。
2. 选择明确的 Skill 和目标 Agent，首次分发验证优先使用 project / copy。真实接管优先使用现有 `import-skill` 固定候选和准入，再走当前 Hermes 受控安装与人工 Grant 流程；`admit <目录>` 仅是静态准入入口，不能替代安装事务或 runtime 激活。其他平台能力分别验收，本文不提供绕过现有授权流程的自动安装包装器。
3. `SKILL.md` 中的 `${HERMES_SKILL_DIR}` 是 Hermes 场景的路径示例，跨平台使用应定位实际安装根；通用脚本以自身位置解析资源。保持现有签名 payload 原样，不为改善文案直接重写已签名内容。
4. 默认需要已有二进制。当前 resolver 支持 `SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1` 的显式下载路径，并先验证签名 manifest；Skill 文案中的历史“never downloads”说明不能替代实际脚本和当前发布范围。验证本轮分发不触发该路径，也不保证旧 manifest 中引用的制品当前可获取。
5. 二进制准备、适配器安装、人工授权和服务健康分别验收。平台能力以[现有能力矩阵](../agentshield-capability-matrix-v1.md)及其证据为准。

## 后续接入的具体边界

以下依据本轮基线 `1e20635843c0966e24d73d149e3d7bcd080f89c4`，区分 SIQ 既有能力与尚未完成的 **vercel CLI 接入**；不能把外部分发的接入缺口视为整个产品的能力缺失：

| 项目 | 现状 | 后续验收要求 |
| --- | --- | --- |
| 共享内容与平台安装关系 | inventory 已有目录稳定的 `installation_id`、平台中立的 locator 和配置推导的多消费者 `Relationships`；`.agents/skills` 仍在 OpenClaw/Trae 已知目录规则中，symlink 被显式拒绝并记录 skipped | 在既有身份系统上适配上游 canonical 内容与各 Agent 投递位置；不把 inferred 关系视为实际执行，不全面放开 symlink 跟随 |
| 来源身份 | `admit` 仍接本地目录；`import-skill` CLI/API 已支持本地目录、ZIP、公开 HTTPS ZIP，固定候选并准入，其中 HTTPS ZIP 支持归档子路径和可选 `expected_sha256`；原生 Git ref 解析与上游 lock 可信绑定尚未提供 | 在既有导入记录上关联 repo、不可变 commit、Skill 子路径、最终树摘要、工具版本及 admission；ZIP URL 和 lock 声明不能自动成为已验证 Git 身份 |
| 安装/更新闭环 | Hermes 受控路径已有固定导入、人工 Grant、安装计划/确认、内容读回、更新替换与恢复；更新处理旧授权后投递候选，新版本不自动激活 runtime。已绑定安装的 runtime 引用每次重验内容，成功结果不缓存。上游 add/update 尚未接入该路径 | 复用现有 import/skillinstall 合同，将上游解析与投递纳入同一内容身份；覆盖直接 add/update、默认 symlink、失败恢复及其他平台。本轮未验证上游安装前 policy callback |
| 不经安装的消费入口 | `skills use` 是临时内容/prompt 入口 | 准入入口与运行时工具授权分别覆盖，不能仅包装 `skills add` |
| 外部 audit 与 lock | 上游 audit 是 advisory，lock 是来源/更新信息 | 作为不可信外部线索记录，不能产生 SIQ effective 权限或替代本次字节的准入 |

本地实现依据：[安装身份与关联](../../apps/agentshield/internal/inventory/discovery.go)、[导入 CLI](../../apps/agentshield/cmd/agentshield/skill_import.go)、[远端导入](../../apps/agentshield/internal/skillimport/remote.go)、[更新事务](../../apps/agentshield/internal/skillinstall/update_operation.go)、[逐次 runtime 校验](../../apps/agentshield/internal/skillinstall/runtime.go)及其[失效测试](../../apps/agentshield/internal/skillinstall/runtime_test.go)。这些是本轮只读核查的既有实现，不是本轮新增或实测的 runtime 保障。

针对 vercel CLI 接入应新增或复用负向用例：扫描后内容替换、上游过滤文件导致摘要变化、目录 symlink 被物化、可变 ref 更新、损坏 lock、直接 `update/use` 绕过受控入口、失败安装回滚。它们使用新实验身份，不能混入既有 V5 分母。

## 本轮验证结果

2026-09-12 在 macOS / Node.js v24.21.0 上完成四个目标的真实上游 CLI 验证；每个目标的 28 个文件内容和可执行位均一致，卸载清除自身目录和 lock 条目，保留其他 Skill。三项 Node 权限负向探针按预期拒绝，46 项 research 单测及 ruff 通过。参见[证据索引与全部尝试](evidence/skills-distribution-20260912/README.md)；最终报告为 attempt-4，之前的失败与中间版本报告保留原样。

Linux/macOS CI 已配置，尚未在 GitHub Actions 上运行。原始实测先于本轮提交，报告中的来源 commit 和工具摘要保持原样。vercel CLI 到既有安装/更新准入流程的接入仍是后续工作。

## 从 Vercel 与 Google 借鉴什么

Vercel 提供通用分发 CLI、明确的 Agent 目录适配和安装/卸载生命周期。本轮据此验证四个投递目标；固定全部包摘要、严格目录比较、权限负向探针与失败证据保留，则是结合 SIQ 安全要求新增的验证措施，不能说成上游已经提供同等安全保证。

2026-09-12 另行只读核查了 Google 的 Skill 内容库，基线为 [150f8525e7e3329603b18d23a0f434aa29137eda](https://github.com/google/skills/tree/150f8525e7e3329603b18d23a0f434aa29137eda)。其 [README](https://github.com/google/skills/blob/150f8525e7e3329603b18d23a0f434aa29137eda/README.md) 也使用 Vercel CLI 分发。对 SIQ 的优先建议是：在现有内容一致性验证外增加静态内容门禁；做有/无 Skill 的行为对照评测；为 Skill 记录维护责任和兼容版本。这些借鉴项本轮仅评估，未宣称已实施。

Google 的[官方工程实践说明](https://cloud.google.com/blog/topics/developers-practitioners/behind-the-scenes-how-we-build-test-and-scale-google-agent-skills)介绍了 metadata/链接检查、定期对照评测和 owner 机制，同时明确公开导出会移除内部评测套件。因此可借鉴方法，不能假设仓库提供完整、可直接移植的内部 CI/eval 框架。

在具体流程写法上，可参考 [IAM 变更后读回](https://github.com/google/skills/blob/150f8525e7e3329603b18d23a0f434aa29137eda/skills/cloud/iam-helper-for-policy-management/SKILL.md)和[模拟失败不视为安全](https://github.com/google/skills/blob/150f8525e7e3329603b18d23a0f434aa29137eda/skills/cloud/iam-helper-for-policy-simulator/SKILL.md)。SIQ 应把这些写法转化为可测试的操作指引；模型输出和 Skill 文本仍不能产生 effective 权限。本轮未安装 Google Skill、引入云服务依赖或改写签名 Skill payload。

## 升级上游版本

人工审阅上游源码和依赖锁，重新从官方 registry 核对每个 artifact 的 integrity 与 SHA-256，并更新 pin。先跑全部离线测试，再执行新的真实 CLI smoke，检查所有失败与差异。GitHub Actions 使用固定 commit，workflow 不自动更新依赖或发布产物。MIT 及其他上游依赖许可留在临时下载的包内；本仓仅保存来源和摘要，不再分发这些包的源码。

源码依据：[发现逻辑](https://github.com/vercel-labs/skills/blob/d667282815248da03a08a18272b5d2eef9caf77c/src/skills.ts)、[安装与复制](https://github.com/vercel-labs/skills/blob/d667282815248da03a08a18272b5d2eef9caf77c/src/installer.ts)、[本地 lock](https://github.com/vercel-labs/skills/blob/d667282815248da03a08a18272b5d2eef9caf77c/src/local-lock.ts)、[audit 展示](https://github.com/vercel-labs/skills/blob/d667282815248da03a08a18272b5d2eef9caf77c/src/add.ts)、[临时使用](https://github.com/vercel-labs/skills/blob/d667282815248da03a08a18272b5d2eef9caf77c/src/use.ts)。
