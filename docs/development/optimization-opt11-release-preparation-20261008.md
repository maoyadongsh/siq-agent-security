# OPT-11 企业连接器安装与升级候选准备

日期：2026-10-08。分支 `codex/security-optimization-20261007`；DGX Spark / Linux arm64。

## 当前结论

已生成两份可供签发评审的企业候选包和候选目录之外独立构建的验证器，完成制品身份、
原生开发入口与签名拒绝预检。**候选未签名、不可安装、未发布；OPT-11 保持 implementing，
总体仍为 11/16（68.75%）。**

个人客户端历史 0.4.0 签名包不是 `enterprise-release/v1`，不能代替企业 Edge/Connector 包。
两个候选使用相同源码、不同预发布版本，提供后续合法更新测试的不同制品字节；
不据此宣称真实设备升级、systemd 服务切换或旧身份迁移已成功。

## 候选及签发评审材料

固定源码：`a9a8e91e7f7701363f8a99328dd573e402c43fb6`。范围为 Edge、Hermes/OpenClaw/Directory
连接器和许可证，共 285 个已提交文件。工作区未提交的 `edge/agent/crash_recovery_test.go`
和其他无关修改未进入候选。

| 材料 | 定位 |
| --- | --- |
| 源码清单 | [285 个 Git 对象输入](evidence/optimization-20261007/enterprise-reviewed-source-inventory.json) |
| 候选 1 | `0.1.0-opt11.20261008.1`；[精确待签输入](evidence/optimization-20261007/enterprise-candidate-1.signing-input.json) |
| 候选 2 | `0.1.0-opt11.20261008.2`；[精确待签输入](evidence/optimization-20261007/enterprise-candidate-2.signing-input.json) |
| 制品、验证器及测试摘要 | [机器可读证据](evidence/optimization-20261007/enterprise-release-preparation.json) |

本机完整候选位置：

```text
/home/maoyd/siq-artifacts/optimization-20261008-enterprise/a9a8e91e-candidate-1/
/home/maoyd/siq-artifacts/optimization-20261008-enterprise/a9a8e91e-candidate-2/
```

每个候选含 Linux amd64/arm64 ×（edge-agent、hermes、openclaw、directory）8 个 ELF、
许可证、CANDIDATE.json、publisher-signing-input.json、ZIP 和 SHA256SUMS。
没有 release.json 或 READY，不覆盖历史签名/发行目录。
构建器以 Git archive 导出，并与事先从 Git blob 固定的清单核对；该清单固定与打包结果分开完成，
不称为外部第三方或独立人工审查。

精确待签输入 SHA-256：

```text
候选 1  b2c0d74f0b9f5120eca301630a4af64ffda7ea02230d0962164bfa3ca229ea80
候选 2  929b31cd0f2e2316ca7e78838f0fc459529913e94fafc4b9583228745dcbba51
```

签发评审须核对版本、源码、制品摘要和原发布身份。待签输入不含签名，不得改名当作发行信封，
也不得借用历史签名。本轮未查找或读取发布私钥，未修改验证器信任根。

## 独立验证器

验证器从同一固定提交另行导出并构建，未从待签候选复制：

```text
var/optimization-20261007/opt11-release-preparation/independent-edge-verifier
SHA-256 c38efcb3dd56aa1ae66c835d0c723ea3f26ff1d468b97138dc926f4568126298
```

构建使用离线 Go 环境与 `-mod=readonly -buildvcs=false -trimpath`；验证器当前为 0500。
“独立”仅指候选外构建、摘要固定和不采用候选自带验证器，不代表另一个实现、编译器或第三方审计。
编译内固定公钥仍为原发布者公钥。

## 已执行的预检

| 检查 | 实际结果 |
| --- | --- |
| 全制品与压缩包 | 两包共 16 个 ELF 的架构/长度/摘要正确；SHA256SUMS、ZIP 每项内容与散文件一致 |
| 原生版本读回 | ARM64 的三个连接器 × 两版本，共 6 次真实 describe，版本与候选一致 |
| 显式开发扫描 | 两个原生 Edge 各扫描一次临时合成 SOUL.md，范围验证、候选/证据和 checkpoint 正常 |
| 签名拒绝 | 两包的未签名输入与零签名伪造信封均被独立实际验证器拒绝 |
| 安装拒绝 | 合法当前安装计划的只读预览成功；实际 setup-enterprise 对伪造发行在 prepare 阶段拒绝 |
| 副作用观察 | 自有 loopback 接收端未收到注册请求；临时 HOME 无身份/配置，暂存父目录为空 |
| 签后组包拒绝 | 实际 enterprise_finalize 使用独立验证器拒绝伪造信封，不产生最终输出目录 |

开发扫描使用新临时 HOME 与合成资料，没有访问日常配置、设备凭据或模型。拒绝用例没有绕过验签，
安装范围确认仅针对合成测试计划。临时接收端、目录和子进程已退出；候选和独立验证器保留供评审。

## 固定源码回归与初始失败

从最小生产导出运行 Edge 全套时，211 个顶层测试通过，9 个顶层测试因缺测试专用文件失败，
2 项条件跳过。缺失的是导出范围之外的 4 份合同向量与固定发布公钥来源文件。

随后只从同一提交补入这 5 个测试输入，重跑原失败的 9 个顶层测试，全部通过。
候选、生产源码和独立验证器均未改变，没有重跑已通过的无关测试。
最终按测试标识去重为 **220 个顶层通过、2 项条件跳过**；包含子测试的通过事件为 **689**，
不能与顶层数字相加。不是“一次全量命令返回成功”；原失败日志完整保留。

条件跳过：`TestInstallPlanWireParity`、`TestSkillAncestryNativeExport`，没有设置其外部样例条件。
测试输入摘要与前后日志摘要记录在公开证据中。此批无生产代码改动，未重复前端/控制面测试。

原始材料：`var/optimization-20261007/opt11-release-preparation/`，包含两个构建日志、
固定源码清单、额外测试输入清单、前后 Go JSON 日志、原生预检脚本与结果。
可复现构建工具仍为 `scripts/release/enterprise_candidate.py`，未新建签发流程。

## 接续验收及仍未满足的条件

1. 获得原发布身份对精确候选材料的有效签名，或核实本机既有企业签名包及受控签发入口。
   不把 `signed_by` 字段或公开摘要当作签名。
2. 使用上述独立验证器核对签名与所有制品，再走既有签后组包工具。签名和组包成功仍不代表安装成功。
3. 在一次性设备状态及独立控制面上完成签名安装、合法更新、旧注册身份迁移、任务执行与失败恢复。
   当前 `install-user-service` 对不同既有 unit 明确拒绝覆盖；完整服务升级/回滚路径尚未验收，
   不能仅切换连接器摘要或更换测试配置目录就宣称真实升级完成。
4. 分别记录 Linux arm64、Linux amd64、Windows 和 macOS 的适用行为。此批 amd64 仅交叉编译；
   现行企业受管执行不支持 Windows/macOS，保留明确 unsupported 与开发路径的不同口径。

签发及平台资源的缺失不影响继续开发未完成的升级与恢复路径。本批仅为 OPT-11 后续验证提供
具体、可核对的候选，未推送远端、未发布、未安装常驻服务，也未将整个优化目标标记完成。
