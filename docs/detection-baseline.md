# 威胁检测基线（P0-3 检测覆盖率 / 阈值 / 脱敏基线）

> 日期：2026-08-20。规则源：`apps/control-api/app/data/threat_rules.v1.json`（签名规则包，加载与校验见 `app/rulepack.py`）；测试：`app/tests/test_threat_analysis.py` + `app/tests/test_threat_rulepack.py` + `app/tests/test_detection_baseline.py`（语料驱动的量化基线，见下方"量化基线"一节）；跑分命令：`uv run pytest app/tests/test_threat_analysis.py app/tests/test_threat_rulepack.py app/tests/test_detection_baseline.py -q`。

## 目的

`docs/eval-baseline.md` 把"确定性分类器"的召回/误报写成了测试锁死的诚实数字。威胁检测是另一条独立流水线（静态扫描 → Finding → 自动隔离），同样需要一份不自吹的基线：规则清单到底覆盖哪些行为、测试到底锁住了哪些规则、自动隔离阈值排除了哪些规则、脱敏到底盖住了哪些密钥格式——好让"新增/修改一条规则"有明确的验收口径，而不是凭感觉改正则。

## 规则清单总览（25 条，2026-08-20 实测，见 `app/data/threat_rules.v1.json`）

| 类别 | 规则数 | rule_id（severity / confidence） |
| --- | --- | --- |
| 下载即执行 | 2 | download-exec-pipe（critical/0.95）、download-exec-powershell（critical/0.95） |
| 凭据访问 | 5 | cred-ssh（high/0.9）、cred-dotenv（high/0.85）、cred-system-files（high/0.9）、cred-cloud（high/0.9）、cred-browser-store（high/0.85） |
| 持久化植入 | 5 | persist-crontab（high/0.9）、persist-systemd（high/0.9）、persist-launchd（high/0.9）、persist-shell-rc（medium/0.8）、persist-run-key（high/0.9） |
| 混淆/动态执行 | 4 | obf-base64-pipe-exec（high/0.9）、obf-eval-dynamic（high/0.85）、obf-base64-blob（medium/0.6）、obf-py-marshal（high/0.85） |
| 网络/外传 | 3 | net-reverse-shell（critical/0.95）、net-hardcoded-c2（high/0.8）、net-webhook-exfil（medium/0.7） |
| 提示注入 | 1 | prompt-injection（high/0.9） |
| Python 文本规则（AST 兜底层，见下节） | 4 | py-os-system-regex（high/0.9）、py-subprocess-shell-regex（high/0.85）、py-ctypes-regex（medium/0.8）、py-dangerous-import（high/0.9） |
| 硬编码密钥字面量（R-7 新增） | 1 | cred-hardcoded-secret（high/0.9） |

**严重度分布**：critical 3 / high 18 / medium 4 / low 0（当前无 low 级规则）。

## 双层检测：正则规则 + Python AST（含重叠计数，2026-08-20 实测验证）

`app/threat_analysis.py` 对 Python 内容额外跑 `_python_ast_checks`（`ast.parse` 树检查），产出 4 条**不在签名规则包内、硬编码在代码里**的规则：`threat-py-os-system`（high/0.95）、`threat-py-subprocess-shell`（high/0.9）、`threat-py-ctypes-load`（medium/0.8）、`threat-py-syntax-parse-failed`（medium/0.75，AST 解析失败时的告警）。这 4 条**不能**通过规则包热更新调整，改动需要发代码。

其中 3 条与规则包里的文本正则规则语义重叠、**会对同一行为各生成一条独立 Finding**（已用 `analyze()` 实测验证，非推测）：

| 行为 | 正则规则（规则包，可热更新） | AST 规则（代码硬编码） |
| --- | --- | --- |
| `os.system(...)` / `os.popen(...)` | `threat-py-os-system-regex`（0.9） | `threat-py-os-system`（0.95） |
| `subprocess.run(..., shell=True)` | `threat-py-subprocess-shell-regex`（0.85） | `threat-py-subprocess-shell`（0.9） |
| `ctypes.CDLL(...)` 等动态加载 | `threat-py-ctypes-regex`（0.8） | `threat-py-ctypes-load`（0.8） |

例：`os.system('ls')` 一行代码 → `match_count = 2`（`threat-py-os-system-regex` + `threat-py-os-system`）。这是有意为之的纵深防御（正则兜底非 Python 场景/AST 解析失败场景，AST 提供更高置信度的精确判定），**不是 bug**，但意味着 Findings 列表里这三类行为的"命中数"存在 2 倍计数，人工复核/统计时需知悉，避免误判为两个独立问题。`threat-py-dangerous-import`（`__import__` 动态导入）没有对应 AST 规则，只有单层覆盖。

## 测试覆盖率基线（诚实边界）

| 覆盖维度 | 数量 | 说明 |
| --- | --- | --- |
| 有直接正样本单测的规则包规则 | **25 / 25** | `test_rule_positive` parametrize 逐条给命中语料并断言 rule_id、行号、excerpt 长度、confidence 范围（含 4 条 Python 文本正则变体） |
| AST 规则测试覆盖 | **4 / 4** | `TestPythonAstChecks` 覆盖 `os-system`/`subprocess-shell`/`ctypes-load`；`threat-py-syntax-parse-failed` 由 `test_syntax_error_silent` 显式断言 |
| 负样本护栏（防误报） | 9 | `test_rule_negative` parametrize：下载落盘非管道、非私钥路径、非 rc 文件、解码落盘非执行、正常 API 调用、短字符串不构成密钥格式等 |
| 脱敏覆盖率断言 | 7 次执行 | `TestRedactionCoverage`：5 组硬编码密钥格式 + PEM 头部单独 + 无关规则命中不受脱敏影响，见下节 |
| 自动隔离阈值边界回归 | 1（本轮新增） | `test_scan_high_severity_low_confidence_no_auto_quarantine`，见下节 R-8 |

## 量化基线（语料驱动，`app/tests/test_detection_baseline.py` + `fixtures/threat/corpus.json`）

上面几节回答"规则/测试各自覆盖了什么"，本节回答一个更接近产品验收的问题：**把全部规则当成一个整体扫描一批更接近真实文件的样本，召回率/误报率是多少**——方法论对齐 `docs/eval-baseline.md` 对分类器的做法（先诚实基线，再谈提升），只是评测对象换成威胁检测引擎。语料是人工构造（每条规则一个包了 2-6 行上下文的样本，而非裸单行），**不是野外恶意样本的统计分布**，这一点在下面如实注明，不冒充更强的结论。

跑分命令：`uv run pytest app/tests/test_detection_baseline.py -q`；数字随代码自动生成到 `app/tests/fixtures/threat/report.json`，与本节手工维护的表格必须一致（`test_detection_baseline_report_written_with_current_scores` 断言召回/误报数字，防止两者漂移）。

**当前基线分（2026-08-20 实测）**：

| 指标 | 值 | 说明 |
| --- | --- | --- |
| 恶意语料规模 | 25 条 | 覆盖全部 7 大类：下载即执行/凭据访问/持久化/混淆/网络/提示注入/Python 高危调用，每条内置规则恰好 1 个样本 |
| 总体召回率 | **25/25 = 1.0** | 25 条内置规则各 1 个带上下文的正样本；与 `test_rule_positive` 单行语料形成双锁 |
| 分类别召回率 | 7/7 类别均 1.0 | `recall_by_category`：download-exec/credential-access/persistence/obfuscation/network/prompt-injection/python-dangerous |
| 良性语料规模 | 12 条 | 与任一威胁规则语义无关的正常运维/开发脚本（只读 crontab/systemd 状态查询、参数数组形式 subprocess、IAM 角色型 boto3、prose 提及 token/password 但非字面量等） |
| 意外误报率（surprise） | **0/12 = 0.0** | 12 条良性语料零命中 |
| 已知误报（单独统计，不计入上一行） | 1 条：`fp-socket-bind-tuple` | `threat-net-hardcoded-c2` 对合法 `sock.bind(("0.0.0.0", 8080))` 的过泛匹配——与上一节"自动隔离阈值"里记录的同一个已知限制，语料化后作为回归锁定（若该规则未来收窄到不再误判 bind，测试会失败提醒同步更新语料与本文档，而不是静默完美） |

**诚实边界**：语料是"每条规则一个精心构造的命中样本"，召回 100% 在方法论上更接近"规则本身没有退化/被误改坏"的**冒烟回归**，而不是"面对未知野外样本的检测能力"评测——后者需要真实/半真实恶意样本集（见"后续"）。误报率的 12 条良性语料同理：覆盖的是"常见开发者会写的正常脚本模式"，不是穷举。

## 自动隔离阈值基线（R-8，`app/routers/threat.py::AUTO_QUARANTINE_MIN_CONFIDENCE = 0.85`）

自动隔离条件：命中的 `severity ∈ {critical, high}` **且** `confidence >= 0.85`。在 21 条 critical/high 规则中：

- **20 条**满足门槛，命中即可触发自动隔离（联动吊销 `RuntimeBinding` + 阻断部署）；
- **1 条被有意排除**：`threat-net-hardcoded-c2`（high / confidence 0.8）——其 `("IP", port)` 元组正则同时匹配任何普通 socket 绑定代码（例如 `sock.bind(("0.0.0.0", 8080))`），并非硬编码 C2 特有语法；命中仍生成 Finding 供人工复核，但不再自动隔离生产部署。

本轮补齐了此前缺失的 API 层回归测试 `test_scan_high_severity_low_confidence_no_auto_quarantine`（`app/tests/test_threat_analysis.py`）：以 `sock.bind(("0.0.0.0", 8080))` 为语料，断言产生 `threat-net-hardcoded-c2` Finding 但 `quarantine_case` 为 `None`——这正是 R-8 收紧阈值要保护的场景，此前只有单元层的规则命中测试，没有 API 层"确认不误隔离"的直接断言。

**已知粒度局限**：`AUTO_QUARANTINE_MIN_CONFIDENCE` 是全局单一常量，不能按规则单独设置阈值；若未来某条规则需要"高置信但业务上仍不希望自动隔离"，目前只能通过下调该规则包里的 `confidence` 字段间接实现，语义上不够直接（见"后续"）。

## 脱敏覆盖率基线（R-7，`redaction_patterns` 字段，规则包内 11 条）

`app/rulepack.py` 把脱敏正则与检测规则放进同一份 Ed25519 签名规则包（`_parse_redaction_patterns`），版本化、可整包热更新；外部包省略该字段时退回内置默认值（与检测规则更新解耦）；字段一旦提供，校验严格度与 `rules` 一致——任何一条不可编译/缺字段即整包拒绝（fail-closed，不允许"部分脱敏规则失效"的半生效状态）。

当前内置 11 条脱敏正则覆盖：`sk-*`（OpenAI 风格）、`gh[pousr]_*`（GitHub）、`Bearer <token>`、`password=`/`token=`/`secret=` 字段级赋值、`aws_secret_access_key=`、裸 `AKIA*`（AWS Access Key ID）、裸 `xox[baprs]-*`（Slack）、PEM 私钥块（BEGIN 头部即命中，END 可选）、JWT 三段式。

`excerpt_sha256` 始终基于**脱敏前原文**计算（保留取证定位能力，见 `_make_match`），只有人可读的 `excerpt` 字段（≤40 字符截断）经脱敏——`TestRedactionCoverage` 用 5 组真实密钥格式 + PEM 头部单独场景验证 `excerpt` 不含原始密钥、`excerpt_sha256` 仍可比对，另有 1 个场景验证脱敏不误伤无关规则的命中片段。

## 已知局限（不隐藏风险）

1. **静态正则黑名单的固有局限**：可被刻意的编码变形/字符串拼接/跨行拆分绕过（例如 `threat-obf-base64-blob` 的 240 字符连续阈值可被人为插入换行绕过，`docs/compatibility.md` 已记录）；静态规则从设计上就不是对抗自适应规避的终态方案，需配合执行后端的运行期行为管控兜底，而非唯一防线。
2. `AUTO_QUARANTINE_MIN_CONFIDENCE` 为全局常量，无法按规则粒度单独配置（见上节）。
3. 正则/AST 双层对 `os.system`/`subprocess(shell=True)`/`ctypes` 三类行为各生成一条独立 Finding，人工复核时的"命中数"存在 2 倍计数（见"双层检测"节），已如实记录，避免被误判为两个独立漏洞或规则缺陷。
4. 脱敏仍是黑名单方案：未覆盖的密钥格式（如自定义内部令牌前缀）不会被脱敏，`excerpt` 即便截断到 40 字符也存在残留敏感片段的风险，应作为纵深防御的一层而非唯一防线。

## 变更与再跑分流程

1. 改规则：编辑内置包 `app/data/threat_rules.v1.json`（走正常代码评审）或部署 Ed25519 签名的外部包（`SIQ_AS_THREAT_RULEPACK_PATH` 指向路径 + 同名 `.sig`），`version` 必须严格递增，否则被拒绝并回退内置包；
2. 新增/修改规则时同步评估：是否需要新增正/负样本测试（`test_rule_positive`/`test_rule_negative`）、是否落入 `AUTO_QUARANTINE_MIN_CONFIDENCE` 的排除范围、是否需要更新本文件的规则清单表格与覆盖率数字；
3. 提交前跑 `uv run pytest app/tests/test_threat_analysis.py app/tests/test_threat_rulepack.py app/tests/test_detection_baseline.py -q`；规则数/覆盖率数字变化必须同步更新本文件（与 `docs/eval-baseline.md` 同样的纪律：语料/规则变更不同步更新文档即视为文档腐化）。

## 后续

- 评估是否需要规则级（而非全局单一常量）的自动隔离置信度阈值配置；
- 评估 `threat-obf-base64-blob` 等启发式规则的跨行拼接/编码变形鲁棒性，是否需要归一化预处理（如去除换行后再匹配）而非仅逐行匹配；
- SIQ 真实语料（依赖跨仓 D3-D5）就绪后，用真实 Agent 产物重跑本基线，对照当前基于合成语料的数字。
