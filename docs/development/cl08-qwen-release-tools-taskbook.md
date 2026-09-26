# Qwen3.8：企业发行工具收口任务书

将本文件完整内容交给 Claude Code / Qwen3.8 执行。

你是本项目的交付工具开发工程师。请直接完成任务，不要只输出建议。

任务编号：CL-08-RELEASE-TOOLS-CLOSEOUT。项目目录：`/home/maoyd/siq/siq-agent-security`。

## 1. 目标与边界

用户要求减少重复测试、禁止扩展功能、加快收口。本任务只核对和修复现有企业候选包、签后组包工具，交付准确命令和阻断清单。不设计第二套工具、不新增安装方式、不升级合同、不实现签名服务。

如果没有可复现问题，可以交付“无需代码修改”；不得为了改代码制造需求。主开发者负责自动接入、后台扫描、资产关系、运行时和权限主线；另一条 GLM 线负责根 README 与生产 runbook。不得越界。

## 2. 开始前必须阅读与检查

- `/home/maoyd/siq/AGENTS.md`、项目根 AGENTS.md、相关目录其他 AGENTS.md（若有）。
- `/home/maoyd/siq/VIBECODING_SCIENTIFIC_METHOD.md`。
- `docs/development/enterprise-auto-onboarding-closeout-20260926.md`，重点 CL-01、CL-08。
- `packages/contracts/enterprise-release.v1.md`。
- `packages/contracts/enterprise-release-candidate.v1.md`。
- `packages/contracts/enterprise-release-finalization.v1.md`。
- `scripts/release/README.md`，以及目标脚本、既有测试和调用方。

执行 `git status --short --branch`，检查目标文件当前 diff。工作树大量改动属于其他开发者，未跟踪文件同样不得覆盖。修改前核对最新内容，不凭提示词假设实现。

## 3. 文件所有权

允许修改：

- `scripts/release/enterprise_candidate.py`
- `scripts/release/enterprise_finalize.py`
- `scripts/release/test_enterprise_candidate.py`
- `scripts/release/test_enterprise_finalize.py`
- `scripts/release/README.md`

允许新增：`docs/development/enterprise-release-tools-closeout-handoff.md`。

其他文件只读。尤其禁止修改共享 `package.py`、`verify.py`、根 README 中英文、生产 runbook、合同、后端、Edge、Connector、前端、Skill 安装脚本、公共台账、依赖及信任根。若修复必须触及禁止文件，记录复现和最小建议，交主开发者处理。

## 4. 具体工作

### A. 来源身份

候选工具必须继续从指定完整 Git commit 导出源码，核对 expected-source-inventory。当前大量最新成果尚未提交，因此 HEAD 构建未必包含它们。必须明确报告这一限制。

禁止自动提交、复制整个工作树替代 Git 导出、伪造 source_commit、跳过 inventory 校验，或将旧 HEAD 产物称为最新完整版本。

### B. 候选包

核对现有 Linux AMD64/ARM64、Edge 与所选 Hermes/OpenClaw/directory Connector、版本注入、路径/大小/摘要/ELF 架构、许可证、ZIP、外层校验清单、输出拒覆盖和离线构建。

保留 signed/installable/published 等真实状态。候选包必须明确未签名、不是正式可安装发行包、未发布、未原生验收。禁止制造占位 release.json 让安装器接受候选包。

### C. 签后组包

核对外部签名与签发输入字节一致、独立 verifier 路径和摘要固定、verifier 不来自候选包、拷贝字节再校验及暂存包复验。错误类型、额外字段、非法响应和非零退出继续失败关闭。

不得执行候选包二进制、覆盖输入、添加跳过签名/摘要/信任根的参数。工具不能注册、扫描、安装、上传或发布。

### D. 命令与错误提示

核对 --help、参数和 README 一致；缺输入返回明确错误及非零状态；错误不输出秘密或环境变量值。交叉编译不能称为原生验收。

只修复复现问题，不做无关重构、格式化或通用框架抽象。保持当前合同、安全判断和授权边界。

## 5. 验证预算

先读两个既有测试文件的运行约定，使用本机已有环境和依赖。调试只跑相关用例，完成时统一跑一次这两个文件。真实缺陷无覆盖时才补最少必要回归；不得删除、跳过或放宽安全断言。

不运行整个前端/后端/Go 全量测试，不新增浏览器验收，不启动数据库或生产服务。可运行无副作用 --help、静态检查、隔离临时目录测试和 git diff --check。

当前源码未冻结且无提交授权，不要求生成正式候选，不读取真实签名材料尝试签发。缺少正式材料应如实记录，不绕过门禁。

## 6. 禁止操作

- 不读取 admin-password.private、真实 .env、密码、令牌、私钥、设备种子。
- 不寻找、读取或调用真实签名密钥。
- 不提交、建分支/标签、推送、发 PR 或修改 Git 配置。
- 不安装依赖、联网下载工具链、启动/重启/部署服务。
- 不注册设备、扫描真实目录、上传数据或操作数据库。
- 不覆盖已有证据/发布包，不使用 git reset、checkout --、clean。
- 不将 mock 验证称为真实签名或生产验收。

## 7. 交付

写入 `docs/development/enterprise-release-tools-closeout-handoff.md`，简洁记录：

1. 实际修改文件；无需代码修改则明确说明。
2. 可复现问题、修复及边界。
3. 实际命令、通过/失败与未运行项目。
4. 来自实际参数定义的命令模板。
5. 候选生成→外部签发→独立验签→签后组包的交接顺序。
6. 正式执行尚缺的材料与授权。
7. 当前未提交成果不在 HEAD 候选包内的提醒。
8. 未提交、未签发、未发布、未部署。

不要复制新总任务书，不宣称 CL-08 或整体完成。最后给出“修了什么、测了什么、还阻断什么、下一步是什么”的简短摘要。
