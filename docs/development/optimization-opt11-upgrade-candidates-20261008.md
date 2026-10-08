# OPT-11：具备恢复协议的企业升级候选准备

日期：2026-10-08。任务保持 **implementing**，总体 **11/16（68.75%）**。

已从固定提交 `63a8cfc063b8c229adc3cade2c6b1754a9e5709a` 生成新的企业候选 `.3`、`.4`。
两份包包含升级与恢复命令、pending 任务阻断和协议探测，均已完成原生预检。
**候选未签名、不可安装、未发布**；没有正式签名安装、真实 systemd 升级或设备迁移的正向结果。

## 为什么替换待签候选

[前期候选](optimization-opt11-release-preparation-20261008.md)固定在 `a9a8e91e`，早于升级恢复实现。
实际调用其两份原生 Edge 的 `upgrade-capabilities` 均返回非零退出码、没有协议 JSON，临时 HOME 未变化。
它们保留原身份与历史证据，不能补写成支持新恢复协议。

新 `.3`、`.4` 使用相同已提交源码和不同预发布版本，验证不同制品身份与恢复协议兼容性；
这不证明两个功能版本之间的收益，也不构成已经完成的安装/升级验收。

## 固定输入与交付位置

源输入共 **297 个 Git 对象文件**，覆盖 Edge、Hermes/OpenClaw/Directory 连接器及许可证。
清单先从 Git blob 独立固定，再与构建器导出比对；未提交的 `crash_recovery_test.go`、
其他协作者工作区修改和本机私密状态不进入包。这里的核对不是外部机构或独立人工审批。

| 材料 | 位置 |
| --- | --- |
| 源输入清单 | [297 个文件摘要](evidence/optimization-20261007/enterprise-upgrade-reviewed-source-inventory.json) |
| `.3` 精确待签输入 | [enterprise-candidate-3.signing-input.json](evidence/optimization-20261007/enterprise-candidate-3.signing-input.json) |
| `.4` 精确待签输入 | [enterprise-candidate-4.signing-input.json](evidence/optimization-20261007/enterprise-candidate-4.signing-input.json) |
| 原生预检、制品及日志摘要 | [enterprise-upgrade-candidates.json](evidence/optimization-20261007/enterprise-upgrade-candidates.json) |

完整制品目录：

```text
/home/maoyd/siq-artifacts/optimization-20261008-enterprise/63a8cfc0-candidate-3/
/home/maoyd/siq-artifacts/optimization-20261008-enterprise/63a8cfc0-candidate-4/
```

版本分别为 `0.1.0-opt11.20261008.3`、`0.1.0-opt11.20261008.4`。
每包 8 个 ELF（两种 Linux 架构 × Edge 和三个连接器）、许可证、候选清单、ZIP、SHA256SUMS
和精确待签输入。没有 release.json、READY 或虚构签名；不能将待签输入改名作为发行信封。

待签输入 SHA-256：

```text
.3  47d4e04af9cf824f590a837494e01d9c11dfccb689e33465d29e1d33e66d1690
.4  c8c63679c4cb49ebd0eb58aee02f66d9f569800cd33a528cde3641347c0906c9
```

## 已完成的验证

| 检查 | 结果 |
| --- | --- |
| 两份实际 Edge 协议读回 | version 与各自候选一致；pending_protocol、confirmation_protocol 和 task_lock 精确符合新合同 |
| 制品与归档 | 16 个 ELF 的架构、长度、SHA-256 及两 ZIP 内容/散文件/SHA256SUMS 全部一致 |
| 原生连接器 | 三个连接器 × 两版本，共 6 次 describe 版本核对通过 |
| 原生开发扫描 | 两个 Edge 各扫描临时合成 SOUL.md，得到有效候选、证据及 checkpoint |
| 固定公钥拒绝 | 候选外独立验证器拒绝未签名输入和零签名伪造信封 |
| 安装拒绝 | 当前安装计划可只读预览；伪造发行在 prepare 阶段拒绝，无身份、配置或暂存输出 |
| 副作用观察 | 自有 loopback 接收端注册请求为 0；HOME/暂存目录保持空；接收端及临时目录清理完成 |
| 签后组包拒绝 | enterprise_finalize 使用独立验证器拒绝伪造信封，无最终输出目录 |
| 干净导出升级回归 | **31 顶层 / 131 含子测试通过**；未用 overlay、未提交文件或工作区代码；测试后源清单仍准确匹配 |

干净导出回归仅选择 `^TestUpgrade`，不伪称本批重跑了完整产品测试。
源提交的最终模块回归及限制见[切换/恢复验证](optimization-opt11-upgrade-apply-validation-20261008.md)。

独立验证器从同一 Git 提交另行导出和构建，不从候选复制；使用离线 Go 构建与固定发布公钥。
它与候选共享实现和编译器，“独立”指构建位置、输入和摘要固定，不代表另一种验签实现。

```text
var/optimization-20261007/opt11-upgrade-candidates/independent-edge-verifier
SHA-256 59cade43faac84b6cf4de5f527c86eb9a46511f611cd089424c288e1f9c9e438
```

准备脚本、导出源码、构建/测试日志及原生预检保留在
`var/optimization-20261007/opt11-upgrade-candidates/`；生成工具沿用 `scripts/release/enterprise_candidate.py`，
没有新建替代签发流程。本批没有查找、读取或使用发布私钥，没有改变验证器信任根。

## 接续条件

需由受控签发入口核对并签署上方精确输入，再用候选外验证器核对信封和全部制品，
随后走真实用户服务安装、停服、升级、明确恢复与采集验收。个人客户端历史 0.4.0 包
不适用企业发行合同。当前缺失的签发材料不能用组件替身或临时公钥补成通过。

本批同时只读复核了业务旧 `226/NAMESPACE` 记录和 API 源码入口，未操作业务服务、模型或数据库；
没有消除干净部署限制，也未新增业务测评结果。后续继续收敛该部署及同候选矩阵。
本批仅本地提交，未推送远端或发布制品。
