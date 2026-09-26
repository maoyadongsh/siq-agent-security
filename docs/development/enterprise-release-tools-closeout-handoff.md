# CL-08 发行工具收口交接（enterprise_candidate / enterprise_finalize）

日期：2026-09-26。任务编号 CL-08-RELEASE-TOOLS-CLOSEOUT。范围：只核对与修复现有企业候选包工具和签后组包工具，交付准确命令与阻断清单；不设计第二套工具、不新增安装方式、不升级合同、不实现签名服务。

## 1. 实际修改文件

**无需代码修改。** 四个目标脚本（`scripts/release/enterprise_candidate.py`、`enterprise_finalize.py`、`test_enterprise_candidate.py`、`test_enterprise_finalize.py`）与 `scripts/release/README.md` 均未改动。核对未发现可复现缺陷；不为改代码制造需求。

核对时确认的既有状态（非本任务改动）：

- 四个目标脚本均为未跟踪新文件（`??`），属本收口周期其他开发者在途成果，本任务只读核对，未覆盖。
- `scripts/release/README.md`、`package.py`、`skill_source_smoke.py` 有他人未提交改动（README 已含企业候选/签后组包段落，与本任务核对内容一致）；本任务未触碰。
- 共享 `package.py`、`verify.py`、根 README 中英文、生产 runbook、合同、后端、Edge、Connector、前端、Skill 安装脚本、公共台账、依赖及信任根均未修改。

## 2. 核对结论（A–D）

### A. 来源身份

- `enterprise_candidate.py` 从指定完整 40 位小写 hex commit 导出：`git rev-parse <sha>^{commit}` 后比对，再 `git archive` 仅导出 `SOURCE_PATHS`（`edge/agent`、三个 connector、LICENSE/NOTICE/LICENSES/THIRD_PARTY_NOTICES.md），工作树修改与未跟踪文件不进入候选（测试 `test_real_fixed_commit_cross_build_and_version_stamping` 用脏工作树+未跟踪文件验证）。
- `package.verify_source_inventory` 要求导出源码与独立审阅的 `siq-release-source-inventory/v1` 清单逐文件相等（路径/SHA-256/字节/可执行位），不一致即失败关闭，且发生在任何 Go 构建之前（测试 `test_review_mismatch_prevents_build_and_output` 断言未调用 go）。
- 无伪造 source_commit、无跳过 inventory 校验、无整树复制路径。
- **限制（必须报告）**：当前工作树有 583 个未提交/未跟踪文件（含大量最新企业成果），HEAD 为 `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`。从 HEAD 构建的候选**不包含**这些未提交成果；任何候选都不能称为"最新完整版本"，须先完成评审、源码冻结与提交授权，再以新的审阅 commit+清单构建。

### B. 候选包

- Linux amd64/arm64 双架构 ×（edge-agent + 所选 connector），`--connector` 可重复选子集，默认 hermes/openclaw/directory；重复/非法选择失败关闭。
- 版本经 `-ldflags -X` 注入 Edge `agentVersion` 与 connector `connectorVersion`；旧源码（const 版本）在编译前拒绝（测试 `test_old_constant_version_commit_rejected_before_compilation`）。
- 构建环境白名单化（`GOENV/GOWORK=off`、`GOTOOLCHAIN=local`、`GOPROXY/GOSUMDB=off`、`CGO_ENABLED=0`），`-mod=readonly`，不下载工具链/依赖，不执行候选二进制。
- 每个产物校验 ELF 魔数/64 位小端/机器号、常规文件、大小 1..268435456，记录路径/大小/SHA-256。
- 许可证文件缺失即失败；`CANDIDATE.json` 为 `enterprise-release-candidate/v1`，`signed/installable/published` 恒 false，`native_installation_acceptance=not_run`；无 release.json、无签名、无 READY。
- ZIP 为 `siq-agent-security-enterprise-VERSION-unsigned-candidate.zip`，同名根目录，`package.zip_verified` 逐文件回读核对名称/内容/可执行位，时间戳固定 1980-01-01；外层 `SHA256SUMS` 覆盖全部散文件与 ZIP、不含自身，仅描述性。
- 输出必须是 checkout 外的新目录，`mkdir` 排他创建，拒覆盖；构建在私有临时目录，转移失败留不完整候选供人工检查，绝不产生可安装发行包。

### C. 签后组包

- `enterprise_finalize.py` 先要求签名信封的规范化无签名内容（sorted-key compact ASCII JSON，去 `signature`）与候选 `publisher-signing-input.json` 逐字节一致，不一致失败关闭。
- verifier 必须独立于候选目录（`is_relative_to(candidate)` 拒绝），且调用方显式提供其 SHA-256；verifier 字节先与摘要比对，再拷贝到私有临时目录（0500）后才执行。摘要本身不构成出处证明。
- verifier 以 `--bundle` 对候选目录做全制品核验，要求精确的成功报告：字段集合、值与类型逐一匹配（数值 0/1 不替代布尔），重复/多余键、非法 JSON、超 8192 字节、非零退出均失败关闭（测试 `test_verifier_report_requires_exact_types_identity_and_success` 覆盖 12 组负例）。
- 制品拷贝到私有新 bundle 时按签名大小/哈希复验实际拷贝字节；暂存 bundle 再独立二次核验（`verify` 共调用 2 次）；两次核验任一失败不产生输出目录（测试覆盖）。
- 最终生成 ZIP（`zip_verified` 回读）、`release.json`（= 已签名信封原字节）、描述性 `SOURCE-INFO.json`、`SHA256SUMS`；输出为候选与 checkout 外的新目录，不覆盖任何输入。
- 不执行候选包二进制/脚本，不注册、不扫描、不安装、不上传、不发布；无跳过签名/摘要/信任根的参数；`published=false`、`installation_acceptance=not_run`。
- 真实 Edge 二进制对伪造发布者的信封拒绝且不产生输出（测试 `test_actual_edge_rejects_forged_publisher_without_output`，本机 go1.26.5 实构建 verifier）。

### D. 命令与错误提示

- 两个工具 `--help` 均 exit 0，参数与 README 描述一致（README 段落由其他开发者先行落盘，本任务核对一致，未改）。
- 缺必填参数：argparse 用法提示 + exit 2；非法 source-sha/verifier-sha256 等：固定文案 `enterprise candidate failed; no signed release produced` / `enterprise finalization failed; no publication performed` + exit 1，不输出秘密、环境变量值、子进程 stderr 或路径细节（`package.run` 只报 phase 与退出码）。
- 交叉编译仅证明可构建；README/REVIEW.md/INSTALL.md 均明确交叉编译不是原生安装或安全验收。

## 3. 实际命令与结果

| 命令（仓库根） | 结果 |
| --- | --- |
| `python3 scripts/release/enterprise_candidate.py --help` | exit 0，参数与 README 一致 |
| `python3 scripts/release/enterprise_finalize.py --help` | exit 0，参数与 README 一致 |
| `python3 -m unittest discover -s scripts/release -p 'test_enterprise_*.py' -v` | **17 passed（9 候选 + 8 组包），0 failed**，本机 Python 3.13.12 / go1.26.5 linux/arm64 |
| 缺参/非法参数错误路径（4 组手工触发） | 明确文案 + 非零退出（2/1），无秘密泄漏 |
| `git diff --check -- scripts/release/` | 干净（exit 0） |

未运行（按验证预算与边界）：前端/后端/Go 全量测试、浏览器验收、数据库/生产服务、`test_package.py`/`test_verify.py`（非本任务目标文件）、正式候选生成（源码未冻结、无提交授权）、真实签发（不读取真实签名材料）。

## 4. 命令模板（来自实际参数定义）

```bash
# 1) 候选生成（离线，需已审阅的完整 commit 与源码清单）
python3 scripts/release/enterprise_candidate.py \
  --source-sha <REVIEWED_40_HEX_COMMIT> \
  --expected-source-inventory <REVIEWED_ENTERPRISE_SOURCE_INVENTORY.json> \
  --version <SEMVER> \
  [--connector hermes] [--connector openclaw] [--connector directory] \
  --out-dir <NEW_DIR_OUTSIDE_CHECKOUT>

# 2) 外部签发（受控环境、原发行身份；本工具不执行，见阻断清单）
#    对候选内 publisher-signing-input.json 的精确字节做 Ed25519 签名，
#    得到 enterprise-release/v1 信封（release.json），不得改名候选输入文件。

# 3) 独立验签（独立可信构建的 edge-agent，不来自候选）
<INDEPENDENT_EDGE_BINARY> verify-enterprise-release \
  --release <SIGNED_RELEASE.json> --bundle <CANDIDATE_DIR>

# 4) 签后组包（独立 verifier 路径 + 其审阅 SHA-256）
python3 scripts/release/enterprise_finalize.py \
  --candidate-dir <CANDIDATE_DIR> \
  --release <SIGNED_RELEASE.json> \
  --verifier <INDEPENDENT_EDGE_BINARY> \
  --verifier-sha256 <REVIEWED_64_HEX> \
  --source-sha <REVIEWED_40_HEX_COMMIT> \
  --version <SEMVER> \
  --out-dir <NEW_DIR_OUTSIDE_CANDIDATE_AND_CHECKOUT>
```

## 5. 交接顺序

候选生成（固定审阅 commit + 清单，离线双架构构建，产出 CANDIDATE.json / 二进制 / 许可证 / unsigned-candidate.zip / SHA256SUMS / publisher-signing-input.json）→ 外部签发（受控环境用原发行身份对 signing-input 精确字节签名，产出 release.json）→ 独立验签（独立可信构建的 edge-agent 对信封+全制品核验）→ 签后组包（finalize 复验待签输入一致性、候选全制品、拷贝字节再校验、暂存包二次核验，产出 ZIP/release.json/SOURCE-INFO.json/SHA256SUMS）。

## 6. 正式执行尚缺的材料与授权

1. 源码冻结与提交授权：当前 583 个未提交/未跟踪文件未进入 HEAD；需先评审、冻结并授权提交，再确定候选 source_commit 与审阅清单。
2. 独立审阅的企业源码清单（`siq-release-source-inventory/v1`）：须对冻结 commit 另行评审固定，不能从待签提交临时生成。
3. 受控签发入口与原发行身份授权：本轮未查找/读取私钥，不假定签发入口可用或不可用。
4. 独立可信构建的 edge-agent verifier 及其审阅 SHA-256（不得取自候选）。
5. 原生平台验收资源：DGX/ARM64 首验与 AMD64 第二原生验收（交叉编译不替代）。
6. 发布位置与发布授权、部署切换授权（CL-08 正式交付门禁）。

## 7. 未提交成果提醒

HEAD（`ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`）不含当前工作树的大量最新企业成果（含本收口周期的合同、脚本与文档）。从 HEAD 构建的候选包**不是**最新完整版本；在源码冻结与提交授权前，任何候选都只能称为"基于旧 HEAD 的候选"，不得对外宣称包含最新开发成果。

## 8. 状态

未提交、未签发、未发布、未部署。本文件仅为发行工具核对交接，不宣称 CL-08 或整体 ENT 完成；正式交付仍依赖 CL-01 基线冻结、CL-07 原生验收与上述授权门禁。

## 摘要

- **修了什么**：无。核对未发现可复现缺陷，四个目标脚本与 README 均未改动。
- **测了什么**：两工具 `--help`（exit 0）、17 项既有单测全过（含真实 Go 构建 verifier 的伪造发布者负例）、4 组缺参/非法参数错误路径、`git diff --check` 干净。
- **还阻断什么**：源码未冻结/无提交授权（HEAD 不含最新成果）、缺审阅清单、缺受控签发入口与身份授权、缺独立 verifier 审阅摘要、缺原生双架构验收资源与发布/部署授权。
- **下一步**：等 CL-01 基线冻结与提交授权后，按第 4 节命令模板执行候选→签发→验签→组包；本工具线不越界代为主开发者或 GLM 文档线工作。

## 9. 主开发者复核（2026-09-26）

复核结论：本次发行工具子任务验收通过，未发现需要修改生产代码的可复现缺陷；不代表 CL-08 或正式发布通过。核对了两个实现、两个测试文件、共享源码导出/清单校验函数、三个企业发行合同与命令说明。

- 重新执行 `python3 -m unittest discover -s scripts/release -p 'test_enterprise_*.py' -v`：17 项通过、0 失败（2.666 秒）。包含真实临时 Go verifier 对伪造发布者的拒绝、双架构合成源码构建及模拟组包；不构成真实签发成功或双架构原生安装验收。
- 两个 CLI 的 `--help` 均 exit 0，与现有 README 参数一致。
- 额外用合成的深嵌套 JSON 检查源码清单及签名信封错误路径，两者均按现有逻辑返回固定错误、exit 1，无输出目录；未发现缺陷，未保留额外测试或扩展功能。
- `git diff --check -- scripts/release/ docs/development/enterprise-release-tools-closeout-handoff.md` 通过。本次仅追加本节，发行工具及其既有测试内容不变；共享工具、其他开发线文件未修改。

交付记录中的 583 个文件是原交接时快照，不是稳定数量。复核时 HEAD 仍为 `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`；构建内容以指定的审阅 commit 为准，不包含其后的未提交成果。正式下一步仍是完成源码评审/冻结及取得提交授权，然后准备独立清单、受控签发材料和可信 verifier。缺少真实签发材料的状态是“本轮未验证”，不推断本机不存在密钥或签发入口。

未运行全项目测试，未生成正式候选，未签发、提交、推送、发布或部署。
