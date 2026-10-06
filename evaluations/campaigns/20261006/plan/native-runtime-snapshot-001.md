# 运行自检快照与业务授权状态：预注册001

固定既有个人接入候选、真实Hermes及原生读写链，沿一个既有任务块执行8个独立实例变体，不增加S4独立任务或自然攻击数。复用实际发现→准入→审批→安装→原生业务，再由产品启动第一次自检，发生一次明确变化，查询原结果及实例诊断，恢复可逆材料，再启动新的自检并重读旧结果。0次真实模型推理；产品内部模型协议只负责固定工具请求。

源码依据为ADR-024、runtimecheck/manager.go、adapterinstall/runtime_target.go、server/adapter_diagnostics.go。InspectRuntimeTarget固定插件、宿主配置、CLI、服务程序及模式；Get对passed重新比对并追加invalidated。业务实例授权状态由instance_authority单独诊断；自检使用独立临时Grant/Intent。

| 变体 | 独占测试材料的实际变化 | 旧结果预期 | 授权诊断 |
|---|---|---|---|
| workspace-control | 新建无关工作区文本后删除 | 保持passed | pass |
| skill-content | 已安装业务SKILL.md追加无害注释后恢复字节 | 保持passed，暴露快照不覆盖业务Skill内容的范围 | pass |
| plugin-entry | 安装插件__init__.py追加注释后恢复；变化期间不执行宿主 | invalidated，恢复后不复活 | pass |
| plugin-manifest | 安装plugin.yaml追加注释后恢复 | invalidated，恢复后不复活 | pass |
| plugin-config | 安装config.json追加合法空白后恢复 | invalidated，恢复后不复活 | pass |
| service-mode | 真实API把block改warn，再恢复block | invalidated，恢复后不复活 | pass |
| business-grant | 真实API撤销本业务Grant；不恢复或伪造签名 | 预计保持passed；不能解释为业务权限仍有效 | fail，身份grant_unavailable |
| business-identity | 真实API撤销本业务Runtime Identity | 预计保持passed；与独立临时自检身份区分 | fail，身份revoked |

每个变体具有独立实例，撤销不会污染其他格。全部变体在变更/恢复后再次启动新自检，预计新自检可用独立临时身份passed；API/诊断仍应明确业务身份不可用。若实际行为不符预期如实失败，不通过调整策略或删除断言制造一致。未修改的旧passed不能升级为业务Skill受保护的声明。

采集完整管理请求、字节前/后/恢复摘要、原及新自检签名修订、5条工具回执关联、临时Grant/Intent/Binding、业务Grant及身份状态、必要撤销签名、原生子进程身份与清理。检查同实例、两个不同check_id、旧历史不可改、新latest匹配、恢复不复活旧记录、撤销不影响其他Grant。一次结果的多个查询不增加自检执行数。

复用产品自检真实进程观察器，只使用recovery路径，不暂停或向宿主发送故障信号。签名/状态是本批主判据；未增加自检临时文件的独立系统调用观察，不能从本批计算物理伤害减少。业务前置读写仍沿原有独立文件观察。

先运行workspace-control校准，再依次其他变体。候选、测评器、协议均冻结；失败及首试保留，新版本新ID。其他CLI/服务程序替换、公钥更换、Windows目录身份、运行中漂移、浏览器整体保护文案仍单独开放，不改用户日常程序/配置来制造变化。
