# 真实运行自检：快照失效与业务授权状态

日期：2026-10-06。作者侧实测，8个002变体、16次实际产品自检完成，336/336项检查符合修订预期。沿一个既有任务块，不增加S4独立任务；0次真实模型推理，产品未修改。

**自检通过不等于当前业务授权仍有效。** 本批真实证据显示：插件或服务模式变化使旧自检失效；业务Skill内容漂移使实例授权暂不可用，但旧自检保持passed；明确撤销业务Grant或身份后，授权持续不可用，独立临时身份仍能完成新的自检。这几项状态具有不同含义，必须一起展示和测量。

## 链路与冻结范围

每格采用独立HOME/profile和合成资料，先完成同一候选发现→准入→审批→安装→SEC→原生合法读取/越界拒绝/合法写入；随后产品启动自检A，发生一个预注册变化，读回A及实例诊断，恢复可逆文件或配置，再实际启动自检B，核对最近结果为B、旧A状态保持。两个检查ID、临时Grant/Intent/Binding和真实Hermes子进程均分别采集。

候选`5470ab3780f2-nativefixturefix1`，二进制SHA-256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。目标快照由runtime_target.go和runtimecheck/manager.go定义，业务授权诊断由runtimeidentity/summary.go与server/adapter_diagnostics.go定义；本批相关源码与已查阅工作树一致，并封入协议摘要。所改文件仅属于测试实例；未改日常Hermes程序、配置或业务库。

## 结果

“恢复”对文件和模式是恢复原字节/原值；两项明确撤销不恢复权限。所有格的新自检均独立启动，不是重新展示历史结果。

| 实际变化 | 变化后旧自检 | 变化后授权诊断 / 身份 | 恢复后旧自检 | 恢复后授权诊断 / 身份 | 新自检 |
|---|---|---|---|---|---|
| workspace-control | passed | pass / issued | passed | pass / issued | passed |
| skill-content | passed | fail / grant_unavailable | passed | pass / issued | passed |
| plugin-entry | invalidated | pass / issued | invalidated | pass / issued | passed |
| plugin-manifest | invalidated | pass / issued | invalidated | pass / issued | passed |
| plugin-config | invalidated | pass / issued | invalidated | pass / issued | passed |
| service-mode | invalidated | pass / issued | invalidated | pass / issued | passed |
| business-grant | passed | fail / grant_unavailable | passed | fail / grant_unavailable | passed |
| business-identity | passed | fail / revoked | passed | fail / revoked | passed |

四个invalidated均为`runtime_check_snapshot_changed`；恢复文件或模式后，旧记录不复活，重新检查才产生新的passed。无关工作区文件不影响自检或授权，是用于排除“任何变化都失败”的正常控制。

业务Skill变化期间，签名Grant仍为approved，但实时来源内容复查使实例身份变为grant_unavailable、整体配置诊断incomplete；恢复原字节后身份重新issued。这不是重新批准或重新部署权限。显式Grant撤销将其改为revoked；身份撤销保留签名撤销记录，不会被新自检复活。

所有实例诊断的`runtime_state`仍为unverified。旧自检invalidated时hook_load为unknown；新自检passed后hook_load为pass。业务权限被撤销时hook_load仍可pass、instance_authority为fail，不能合并解释为“已保护且可执行全部业务”。本批检查真实API诊断，未新增浏览器截图或验证所有页面文案。

## 证据与核验

每格27项业务前置检查加15项状态/变化检查，共336项；该分母包含重复的前置流程，不是336个攻击样本。完整链共120条唯一签名回执：40条前置业务记录、80条自检记录。另有100份追加签名自检修订、48份临时权限文件、652次管理HTTP、40次外层固定提议协议请求；产品内部协议请求总数未单独采集，真实供应商推理0次。

八份原冻结核验器全部通过；补充002核验把被改变的业务Grant/身份关联回真实安装批准链，并把每次自检关联到自身签名Binding和独立临时Grant，不能靠ID名称猜测或借用其他自检。11类离线篡改在八份材料上共60次全部拒绝：签名变动、跨实例、借用身份/Grant、重复旧检查、删链前缀、变体替换、恢复旧pass、未实际改变文件、掩盖授权失败及替换撤销响应。离线篡改不是新业务或攻击执行。

32份已记录进程身份（8个守护进程、8个前置业务宿主、16个产品自检宿主）已核对均不存在。自检临时Grant撤销、材料清理完成；文件变化均恢复，明确的业务撤销不反向修复。原有独立业务文件观察器保留，但自检临时探针没有新增外部系统调用观察；因此本报告证明状态和授权关联，不提供新的独立物理伤害减少率。

## 失败与修正保留

001 workspace-control首试41/41。001 skill-content首试40/41：旧方案误以为Skill内容漂移不影响实例授权；实测与源码确认实时内容校验会使其不可用，恢复内容后可用。原数据、退出1及[001协议](../plan/native-runtime-snapshot-001.md)保留；[002协议](../plan/native-runtime-snapshot-002.md)执行前明确修订预期，并增加身份恢复读回。002还按实际批准链把初始业务Grant记为approved，而不是未经依据的deployed。

补充核验器001错误猜测临时Grant名称，导致对有效数据报错；[错误记录](native-runtime-snapshot-review-001-error.json)及冻结源码保留。002改为核对实际签名Binding中的Grant/Intent关联，不改变原数据或原冻结核验。没有通过修改产品或放宽授权获取通过。

测评框架590项测试与118子检查通过，Ruff和文档链接/摘要检查另见工程验证。完整产品验收仍在进行。

## 数据与复跑

| run_id | manifest SHA-256 |
|---|---|
| native-snapshot-workspace-control-002 | `eb107a4d84065208cb8adf0bf235ae8242d71cbe4567592341050e62bea27062` |
| native-snapshot-skill-content-002 | `4f1000ecea0c889531f757e15508b74fb04697a9d3976cbcf6d11683c63ad3e2` |
| native-snapshot-plugin-entry-002 | `7011a299384f1865589bc3667f6c85a5895128e7df30986e8e8f5f2073480ab4` |
| native-snapshot-plugin-manifest-002 | `1d151e4ba01856a13f91d26769126b33e67f0bbc4bdfcef21c0341579fb36e0b` |
| native-snapshot-plugin-config-002 | `01d20dafd39998f407f57e93597e7ee39e99a619722f3ecab69b659172cb6ffc` |
| native-snapshot-service-mode-002 | `eb6fc9ade6c8bbf24c97347710d837785627a226b47296c1881294fe9e8a06e6` |
| native-snapshot-business-grant-002 | `6a8a89832ed3e31986d3901a42b353101b7ddad16cbc6d64cab0d6953b7ee0ce` |
| native-snapshot-business-identity-002 | `656a7ac2ae8a67fa3b256ba6b01a3f7a5b401d8ba2632262a2ec2c4c1f7c5d03` |

原始状态保存在private，白名单导出在`data/<run_id>`；原核验在`protocols/<run_id>-protocol/harness-source`，补充核验在`protocols/native-runtime-snapshot-review-002/harness-source`。各格`reports/<run_id>-verification.json`与`-scope-review.json`可独立阅读；[汇总与资源核对](../inventory/native-runtime-snapshot-integration-002.json)、[执行命令](../REPRODUCE.md)提供复核入口。摘要锚为作者本地保管，不冒充外部取证。

## 对方案的更新及剩余范围

RB09/Q4补齐上述八类变化。后续先复用已有来源异常证据，补缺失的真实导入、固定来源和完整性变体；CLI/服务程序/服务公钥替换、运行中漂移、Windows目录身份以及完整UI呈现仍保持未完成。企业同版本闭环、更多自然模型业务和独立第三方复核不因本批通过而关闭。
