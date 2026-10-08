# OPT-12：安装归属与钩子漂移诊断第一批

日期：2026-10-08。开发基线 `1403543a`，分支 `codex/security-optimization-20261007`。本批完成两项诊断／归属缺陷修复，OPT-12 保持 implementing，全项目已验收 10/16（62.5%）。

## 问题与修复结果

| 触发条件 | 原行为 | 当前行为 |
| --- | --- | --- |
| 已安装后删除整个插件目录／配置根 | Hermes、OpenClaw、WorkBuddy 的组件诊断都可能显示 not_installed | 先核验既有密封安装记录，再检查入口；已有安装而入口缺失返回 incomplete／adapter_files=fail |
| OpenClaw 安装的密封材料损坏，插件本身仍完整 | 诊断可返回 ready | installation_record=fail，配置不再被报告为就绪 |
| 明文 operation 的 action 从 install 改为 uninstall，原结束记录仍匹配 | latestManagedRecord 在验证密封计划前返回“无安装记录” | 先认证密封计划并核对动作与归属；篡改被拒绝，诊断显示 incomplete |

第三行不会凭空授予工具权限，但会错误隐藏安装归属并影响后续安装规划，因此必须修复。上述反例在修复前实际执行失败：三种删除场景、一个密封损坏场景、一个伪造卸载场景。新增正向检查在旧代码也因缺少新诊断项失败，该现象不另外算漏洞。

检查来源是服务二进制内嵌插件与状态目录中的既有密封计划，不接受插件目录替换的新清单作为预期摘要。安装记录通过只表示计划可核对；真实加载、当前权限与执行阻断仍是独立事实。删除钩子可能使宿主不再调用 SIQ，本批不会用“发现漂移”宣称“已经阻断”。

## 验证与证据

公开证据：[结构化验证记录](evidence/optimization-20261007/adapter-installation-integrity.json)。诊断样例：[实际组件生成的 v1 合同样例](../../apps/agentshield/testdata/contracts/adapter-diagnostics-integrity.json)。设计：[ADR-0059](../adr/0059-adapter-installation-integrity.md)。

| 检查 | 结果与口径 |
| --- | --- |
| Go 模块全量 `go test -json ./...` | 1,736 个顶层测试通过、34 个顶层测试跳过；含子测试共4,185个pass事件，不能把父项与子项累加为独立样本 |
| 新完整性测试最终定向运行 | 7个顶层测试通过；覆盖三平台文件层安装／删除／卸载、替换插件清单、伪造卸载、密封损坏、升级中断恢复和样例一致性。与全量有重叠 |
| 管理接口补充回归 | 1项通过；认证管理请求返回钩子缺失，不泄露私有路径、不重建目录；使用真实HTTP处理器和临时状态，不是原生宿主调用 |
| Python 合同样例 | 3项通过；新样例符合现有diagnostics/v1，不能冒充runtime verified或携带凭据 |
| `go vet ./...`、Ruff | 通过；新参数化行首次超长，换行后Ruff通过 |
| 格式 | 所有已跟踪Go源码及本批新测试通过；全目录gofmt另发现原有未跟踪`.tmp/fx01/refcalc.go`，保留不动 |
| 四目标构建 | linux/amd64、linux/arm64、darwin/arm64、windows/amd64通过；程序摘要保存在公开证据中，交叉构建不替代原生验收 |

全量测试启动后，仅把新样例测试从一次性导出改为对照保存的样例，随后定向重跑；新管理HTTP测试另行运行。运行时代码在全量、vet和构建期间没有变动。跳过项包括需要真实Windows/macOS、Hermes/OpenClaw/OpenShell显式配置、系统服务和性能观测的既有测试，不将其计为本批通过。

原始输出在忽略目录 `var/optimization-20261007/opt12-installation-integrity-001/`；公开证据记录日志和候选源码摘要。最初pytest筛选词`adapter_diagnostic`未选中用例，改用`-k diagnosis`后3项通过；空选择不算验收。

## 兼容性与执行边界

- diagnostics/v1 的check code原本是开放类别字符串，本批增加installation_record，不改字段、版本或历史样例。
- 正常安装和卸载仍可完成；合法升级中断返回不完整，显式恢复后回到此前安装。原有共享配置保留、审计失败回滚与异常恢复由全量测试覆盖。
- 历史无受保护事务记录时保留既有兼容检查；不生成新可信身份、不回填历史结果。
- 诊断只读，不执行或导入插件、不自动撤权／安装／重启；runtime_state始终unverified。
- 状态目录密封与独立服务检查不抵抗可替换服务程序或读取备份密钥的同UID攻击者；不自动提升桌面信任档位。
- 没有调用模型，没有修改日常宿主配置、数据库、系统服务或冻结测评。WorkBuddy此处为文件层组件验证，不改变Linux不提供WorkBuddy新接入的产品范围。

## OPT-12剩余任务

仍需完成完整发行制品身份的安装／升级核对、受保护宿主加载位置与实际执行后果验证，并按可用机器记录原生平台结果。现有安装事务与诊断修复不能替代这些证据，OPT-12继续implementing。其他OPT-08／10／11／14／15和最终远端交付门禁保持原任务范围。
