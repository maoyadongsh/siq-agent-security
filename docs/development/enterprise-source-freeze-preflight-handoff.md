# CL-01-SOURCE-FREEZE-PREFLIGHT 交接：源码冻结前只读工作树盘点工具

日期：2026-09-26
状态：**未提交、未推送、未签发、未部署，待主开发者复核**。仅交付冻结前准备工具；**不宣布源码已冻结**，不宣布 CL-01 完成。

## 1. 背景与新工具定位

当前工作树有大量未提交/未跟踪成果（详见 enterprise-release-tools-closeout-handoff.md §6/§7：HEAD 不含最新成果，候选构建必须等评审、冻结与提交授权）。本任务交付一个小型只读、可重复执行的冻结前检查工具，回答三个问题：

1. 准备交付哪些文件（主开发者显式指定的允许清单）；
2. 哪些仍待审阅（工作树中未列入清单的改动/未跟踪条目）；
3. 扫描期间工作树是否发生变化（unstable 判定）。

**与现有发行工具的关系**：检索确认无同类既有工具（E164 冻结是历史候选提交核对；scripts/release 的 `siq-release-source-inventory/v1` 表示**已提交源码**的逐文件身份，由 `package.inventory()` 实现，用于 enterprise_candidate 的导出比对）。本工具报告使用独立合同 `siq-source-freeze-preflight/v1`，只表示**工作树审阅状态快照**，不生成 `release.json`，不写成、也不替代发行来源 inventory。两者不可互换使用。

## 2. 新增文件（全部在白名单内）

- `scripts/enterprise-experience/source-freeze-preflight.py`（工具，Python 标准库，无新依赖）
- `scripts/enterprise-experience/test_source_freeze_preflight.py`（合成仓库组合测试，7 项）
- 本文档

未修改任何公共台账、README、发行工具（scripts/release/*）、产品代码或其他人的交付记录。未发现同名既有文件。

## 3. 工具能力与用法

```bash
# 默认：路径级盘点（只枚举路径与 Git 状态，不读文件正文）
python3 scripts/enterprise-experience/source-freeze-preflight.py \
  --repo /home/maoyd/siq/siq-agent-security \
  --out /tmp/<NEW_DIR>/report.json

# 内容级：仅对显式允许清单中的相对路径计算 SHA-256
python3 scripts/enterprise-experience/source-freeze-preflight.py \
  --repo /home/maoyd/siq/siq-agent-security \
  --allowlist <清单文件，每行一个仓库相对路径，# 为注释> \
  --out /tmp/<NEW_DIR>/report.json \
  [--max-content-bytes N，默认 1048576]
```

要点：

- **Git 只读**：仅 `rev-parse` / `branch --show-current` / `status --porcelain=v1 -z --untracked-files=all` / `ls-files -z --unmerged`，全部带 `--no-optional-locks`（不写索引）；列表参数调用，无 `shell=True`，不执行仓库内任何文件，不 add/commit/stash/checkout/reset/clean、不建分支、不复制工作树。
- **路径解析**：`-z` 输出解析，支持空格、中文、引号及改名条目（R/C 双字段）。
- **内容级读取限制**：拒绝绝对路径、`..` 逃逸、反斜杠、任何路径组件为符号链接（逐段 lstat，不跟随）、非普通文件；`.env`（含 `.env.*`，`.env.example` 除外）、`*.private`、`*.seed`、`*.pem`、`*.key`、`*.p12`、`*.pfx`、`*.kdbx` 及 `backups/`、`var/`、`.git/`、`__pycache__/`、`node_modules/`、`.venv/`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/` 等目录命中即 `sensitive_excluded`——只做排除标记，不读取、不摘要、正文不出现在任何输出；**允许清单不能覆盖敏感路径拒绝规则**；超过 `--max-content-bytes` 报 `too_large_unverified`，不算已核验。
- **一致性**：扫描前后各取一次完整 Git 状态（HEAD/分支/全部条目/冲突）比对，不一致即 `unstable.scan_stable=false`；内容级文件记录读取前后 `dev/ino/大小/mtime_ns` 身份，变化即 `changed_during_read`。报告内注明：**这不是原子文件系统快照，不能消除所有并发写窗口**。
- **输出**：JSON 报告含工具版本、HEAD、分支、工作树状态（含逐条 status entries）、允许清单摘要与逐文件结果（路径/状态/SHA256/大小/mtime）、排除项、未审阅项、缺失项、冲突项、不稳定项、阻断原因。`signed/installable/published` 恒 `false`。报告路径必须在仓库外，`O_CREAT|O_EXCL` 独占创建、拒绝覆盖（退出码 3），权限 0600；错误消息不含文件正文或秘密。
- **退出码**：0=所列文件快照检查通过（无冲突、扫描稳定、允许清单全部已核验）；1=blocked（存在未解决冲突/不稳定/未核验/缺失，**绝不给出"可发行"结论**）；2=用法错误；3=报告写出失败；4=Git 调用失败。工具通过仅表示"所列文件快照检查通过"，**不是发布授权，不表示源码已冻结**。
- **已知边界**：枚举基于 Git 视角——被 .gitignore 忽略的文件（含被忽略的敏感文件）不进入本工具的枚举与排除清单；敏感规则只对"出现在 Git 状态或允许清单中的路径"生效。

## 4. 验证（临时合成仓库，7 项全过）

`python3 scripts/enterprise-experience/test_source_freeze_preflight.py`：**7 passed**（0.79s）。覆盖：

1. 修改/新增/删除/改名（M/A/D/R）+ 空格/中文/引号特殊路径枚举；报告 schema 与 `siq-release-source-inventory/v1` 明确不同；
2. 未解决冲突 → blocked + 非零退出 + conflicts 列出；
3. 显式允许清单 verified（SHA256 与独立计算一致）+ 未审阅条目归类；
4. `.env`/`*.private`/符号链接/`..` 逃逸/绝对路径/缺失条目 → 全部拒绝或标记，秘密标记字符串不出现在报告或 stdout；
5. 大小上限 → `too_large_unverified`、无摘要、blocked、正文不泄漏；
6. 扫描中变动（注入两次 `git_state` 之间修改文件）→ `scan_stable=false`、blocked；
7. 报告拒覆盖（原报告字节不变）+ 输出在仓库内被拒。

测试中的提交/合并只发生在 `tempfile` 合成仓库；未读取真实敏感文件；未运行全项目测试或构建。

## 5. 真实项目实际运行（只读）

| 运行 | 命令 | 结果 |
| --- | --- | --- |
| 路径级盘点 | `--repo /home/maoyd/siq/siq-agent-security --out /tmp/siq-cl01-source-freeze-preflight/preflight-worktree-pathlevel-20260926.json` | exit 0，`snapshot_check_passed`，HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`，分支 main，已跟踪改动 **103** 条、未跟踪 **682** 条、冲突 0、扫描稳定 |
| 内容级示例 | 同上 + `--allowlist /tmp/siq-cl01-source-freeze-preflight/allowlist-task-sources.txt`（仅本任务两个新源码文件） | exit 0，2 项全部 `verified`（`source-freeze-preflight.py` sha256 `39d1b89e…` 14599 字节；`test_source_freeze_preflight.py` sha256 `7fc8b652…` 10087 字节），其余 783 条路径全部进入 `unreviewed` |

报告与允许清单存档：`/tmp/siq-cl01-source-freeze-preflight/`（仓库外，0600）。示例允许清单只含本任务新增的两个文件，**未把任何未跟踪文件自动加入允许清单**。

口径提醒：103/682/783 是本次快照的**路径条目计数**，不是任务数、完成率或审阅进度；不同时点数字必然漂移（既有交接记录中的 583 亦为其当时快照）。

## 6. 未运行项与能力边界

- 未跑全项目测试/构建/浏览器验收（不在本任务范围）；未生成候选包、未签发、未部署。
- 工具不做：任何写 Git 操作、文件内容批量读取、发行来源 inventory 生成、冲突解决、任务归属判定。它不能证明"工作树在此刻之后没有变化"，也不能替代人工审阅。
- 合成仓库验证为 L1 证据；真实项目运行是路径级 L1/L2 快照，不构成生产或发行证据。

## 7. 下一步（主开发者）

1. 依据各责任线交接文档，把待交付文件逐个写入允许清单（每行一个仓库相对路径），分批运行内容级盘点并复核 `unreviewed` 与 `excluded` 列表；
2. 对 `unreviewed` 中每条路径确认责任人（文件→责任线→合同版本→验证结果，对应 CL-01 清单要求）；
3. 全部路径有归属且允许清单核验通过后，再走评审→冻结→提交授权流程；冻结 commit 确定后，按 enterprise-release-tools-closeout-handoff.md §4 模板另行准备独立审阅的 `siq-release-source-inventory/v1`。

## 8. 状态

未提交、未推送、未签发、未部署。仅完成冻结前准备工具及其验证；**源码未冻结**，CL-01 未完成，正式发行仍依赖既有授权门禁。

## 9. 主开发者复核与修复（2026-09-26）

原交付未直接接受。收紧两项原有断言并新增三项集中负例后，原实现实际为
**5 failed / 5 passed**，对应四类问题：

1. 存在 unreviewed 时仍 exit 0；修复为未审阅和排除待审项均阻断，HEAD 不可用也阻断。
2. Git 状态同为 M 的文件在首次摘要后改变，仍被标记稳定；增加结束点内容与身份复核，不匹配清除摘要并列入 unstable。
3. 输出文件尚不存在时，父目录软链接可把报告写入仓库；始终解析输出位置检查边界，写出时逐层目录描述符打开并拒绝软链接，保持独占创建。
4. lstat 后目标被替换为软链接，原 open 仍读到链接目标并算摘要；内容读取改为目录描述符逐段 O_NOFOLLOW，最终文件 O_NONBLOCK、防特殊文件与多硬链接，打开身份不一致即拒绝。读取最多预算加一字节，避免检查大小后增长导致无界读取；不完整或不稳定数据不输出摘要。

同时修正原“仓库内输出拒绝”测试检查了错误路径的问题；输入 NUL 拒绝，预期输入/文件系统错误不输出 traceback。脚本通过 `python` 调用，移除未设置可执行权限的 shebang，并修复本机实际 Ruff 规则发现的局部问题，没有修改规则配置。

验证：

```bash
python -m unittest discover -s scripts/enterprise-experience -p test_source_freeze_preflight.py -q
# 10 tests，全部通过
apps/control-api/.venv/bin/ruff check scripts/enterprise-experience/source-freeze-preflight.py \
  scripts/enterprise-experience/test_source_freeze_preflight.py
# All checks passed
git diff --check
```

真实项目只运行默认路径级盘点，没有允许清单、没有读取源码或秘密正文。
报告：`/tmp/siq-freeze-review-TcAKNd/report.json`，**exit 1 / blocked**；当时 103 个已跟踪改动、686 个未跟踪条目、0 冲突。旧第五节 exit 0 是修复前结果，不能再作为当前门禁通过证据。

边界仍保留：这不是原子快照；结束核对后仍可能变化，不抵御拥有相同用户权限的任意恶意文件系统操纵。允许清单当前为行格式，不能无损表达包含换行或首尾空白的文件名，这些路径必须保留未审阅，不得自动批准。删除/改名前路径及敏感排除项需要人工审阅，工具不会自动使它们通过。敏感识别基于路径规则，不是文件内容秘密扫描器；调用方应仅提供可信的路径清单，不能把凭据文件作为清单输入。内容核验依赖 POSIX 描述符能力，未声明 Windows 已验证。

仅本工具完成上述修复及定向验证；未提交、未部署、源码未冻结，不关闭 CL-01 或签发门禁。
