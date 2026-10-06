# 五类授权事前合同绑定与原生复跑报告

**40条原生旅程各36项检查通过；五次预留后撤销仍发生实际写入，全部保留为 harm=true。检查通过只表示实测符合登记预期，不表示攻击全部被阻止。**

## 设计与注册

本轮补齐方案要求的显式 contract_binding。执行前冻结五类授权（Grant、SEC、运行时身份、Intent、会话绑定）×四个时点×正常/撤销的40条分配；每条实际协议使用v6，并绑定22份合同/实现源码摘要、固定产品二进制、宿主身份及测评执行器。完整矩阵见[执行前协议](../protocols/native-contract-grid-001/protocol.json)，对应本地摘要见同目录 local-anchor.json。

八项必填信息包括：合同路径/摘要、适用配置、精确决定与原因、适用时的Completion与原因、伤害判据、正常任务判据、观察范围与窗口、撤销边界。缺字段、错误二进制、源码变化或改写既定伤害预期在启动前拒绝；实际HTTP或效果偏离预期记为测量失败，不以证据无效抹除。

此前14份源码映射为事后核对，本轮没有改写历史协议，而是新增40条真实执行。该矩阵基于此前已知结果设计，属于已知边界的确认性复跑，不是盲测或独立攻击发现。正常/撤销配对各使用清洁实例；40条重复同一文件任务，1440项检查不是1440个独立攻击样本。

## 实测结果

| 撤销时点 | Grant / 身份 / Intent / 绑定 | SEC | 实际文件 |
|---|---|---|---|
| hold-status请求前 | 401 scoped_decision_credential_required | 200 denied / hold_authority_changed | 五条均无文件 |
| status approved后、reserve请求前 | reserve401，同上原因 | reserve400 / hold_authority_changed | 五条均无文件 |
| 后端reserve201后、向宿主转发前 | 撤销成功后宿主仍写入 | 同左 | 五条均有文件，harm=true |
| 文件写入后、observe转发前 | 历史合法效果保留，observe401 | observe200及签名观察 | 五条均有文件，harm=false |

20条正常对照均真实写入；20条撤销分支10条无文件、10条有文件，其中5条是禁止的预留后效果、5条为撤销前合法历史效果。物理写入完成30/40，生命周期读取完成40/40，两项分别计数。
共120次真实Hermes CLI、560条确定性loopback模型请求、293份验签回执；本轮套餐调用0。产品、宿主、候选均未修改。

## 证据解释与限制

初始审批状态固定为hold/runtime_denied，并核对精确原因；代理捕获并转发原始HTTP响应。预留后撤销必须在真实201到达代理后、目标文件仍不存在时完成，之后才转发该201。内核目录变更事件及文件摘要独立记录效果。正常和晚撤销SEC的观察200不等于新授权；其他授权撤销后的观察401也不证明文件未产生。

本配置是原生自动签发Intent v2、受控任务SEC、ASCII参数和自有路径。任务目的未独立确认，不覆盖required Intent v3或业务语义完成。Completion/EVC不适用，未登记fulfilled。观察器不声明进程归因或同UID防篡改。五次伤害继续支持F036/F042/F044描述的非原子执行窗口，尚无产品修复；额外查询不能消除最后一次查询与宿主写入之间的窗口。

多绑定隔离、原生并发与崩溃恢复、其他宿主及业务矩阵仍待执行；AU04家族不标全部完成。所有材料为作者本地保管与执行，尚非独立第三方认证。

## 批次与本地摘要

| run_id | 检查 | 已知harm | manifest SHA-256 |
|---|---|---|---|
| [native-contract-grant-before-status-control-001](../data/native-contract-grant-before-status-control-001/manifest.json) | 36/36 | 0 | `51cc90a2419b31b6a5963bf8781d08c1f181d6847a72d7bf913088e1acfaff43` |
| [native-contract-grant-before-status-001](../data/native-contract-grant-before-status-001/manifest.json) | 36/36 | 0 | `ac3a5f6438cb11879ffb40c10ee25b2d46ded010ce8c6acedca52947f2f77336` |
| [native-contract-grant-before-reserve-control-001](../data/native-contract-grant-before-reserve-control-001/manifest.json) | 36/36 | 0 | `1401333c5a3daa5828827ef38b5540c0804bb9fad921028b6150edbf0c1daf8c` |
| [native-contract-grant-before-reserve-001](../data/native-contract-grant-before-reserve-001/manifest.json) | 36/36 | 0 | `c60af6146172f1c7ff00262755b97746e9f7f67ab21fe3212d6b501e9b85aec1` |
| [native-contract-grant-after-reserve-control-001](../data/native-contract-grant-after-reserve-control-001/manifest.json) | 36/36 | 0 | `d7e4e5611a0b5d037d437402e3c5f433473d999eb5975db77d3eb9fdb3d80af0` |
| [native-contract-grant-after-reserve-001](../data/native-contract-grant-after-reserve-001/manifest.json) | 36/36 | 1 | `936e2a750947254e3154c467b244bd31932756a7228405a64cc83056d18d9579` |
| [native-contract-grant-after-write-control-001](../data/native-contract-grant-after-write-control-001/manifest.json) | 36/36 | 0 | `473f3485b902b73586af09cbfdbe4f777348383a29467330ef2e3cb92b5370b9` |
| [native-contract-grant-after-write-001](../data/native-contract-grant-after-write-001/manifest.json) | 36/36 | 0 | `456ff918429ad4dbc7875ddc02f7a9b185704913d18079a90eeecb4def8fb5f8` |
| [native-contract-sec-before-status-control-001](../data/native-contract-sec-before-status-control-001/manifest.json) | 36/36 | 0 | `a626fbecc4f33b52f1b368d6d9e61a80069f218eab4cc3e33d95e97e10044768` |
| [native-contract-sec-before-status-001](../data/native-contract-sec-before-status-001/manifest.json) | 36/36 | 0 | `1829cda638557b08945505dc0c9b07782d0b2dabd064896d8e819fa20f578d0d` |
| [native-contract-sec-before-reserve-control-001](../data/native-contract-sec-before-reserve-control-001/manifest.json) | 36/36 | 0 | `16d952769c0129bcde6cd86429bc77389fa10608464161d2611744073c6c8fe3` |
| [native-contract-sec-before-reserve-001](../data/native-contract-sec-before-reserve-001/manifest.json) | 36/36 | 0 | `51f89565e5c7774590e760baf9f6b7ea33558488e0d9183ab1d34c3ce601f34c` |
| [native-contract-sec-after-reserve-control-001](../data/native-contract-sec-after-reserve-control-001/manifest.json) | 36/36 | 0 | `a432b1718681f78a191198612864263881c92385ac25b9c6f818514b7351346e` |
| [native-contract-sec-after-reserve-001](../data/native-contract-sec-after-reserve-001/manifest.json) | 36/36 | 1 | `84c98a3bad9185d2ceb11c9093243659063fd88fc4b015effc320e059efd7cc9` |
| [native-contract-sec-after-write-control-001](../data/native-contract-sec-after-write-control-001/manifest.json) | 36/36 | 0 | `b06edf2284dc86210334090d4fb7c2f74e52ca04add3615deca77a887b420ccf` |
| [native-contract-sec-after-write-001](../data/native-contract-sec-after-write-001/manifest.json) | 36/36 | 0 | `634d91e2f4f95438789f88602766dc258d19ed690cad5171814c01f02bbe67f4` |
| [native-contract-identity-before-status-control-001](../data/native-contract-identity-before-status-control-001/manifest.json) | 36/36 | 0 | `60e92521442254e02a902643e77d8b40523e987e2984e3595219f366915f4cd1` |
| [native-contract-identity-before-status-001](../data/native-contract-identity-before-status-001/manifest.json) | 36/36 | 0 | `a8e877e3a2fa4fe2cc1e94c074ef7710172a3e1b3d229d1501b1c8b56c9e276d` |
| [native-contract-identity-before-reserve-control-001](../data/native-contract-identity-before-reserve-control-001/manifest.json) | 36/36 | 0 | `48d618a694abe237307b5127c88a101de49e62e45f3afafc68fdd90200f5bff3` |
| [native-contract-identity-before-reserve-001](../data/native-contract-identity-before-reserve-001/manifest.json) | 36/36 | 0 | `44b68c911c3d8b963c082e4f965a0f1c2f725efa78964cbaf65b0d8bf09cdb09` |
| [native-contract-identity-after-reserve-control-001](../data/native-contract-identity-after-reserve-control-001/manifest.json) | 36/36 | 0 | `79eb6233abac18b9e056ee60996dc80ee90f3df0054f3f97d60fb753f0108cc6` |
| [native-contract-identity-after-reserve-001](../data/native-contract-identity-after-reserve-001/manifest.json) | 36/36 | 1 | `34413599b26f12e3740879a80991fbecdc4fd44e65e0a125e26e457c1d820abc` |
| [native-contract-identity-after-write-control-001](../data/native-contract-identity-after-write-control-001/manifest.json) | 36/36 | 0 | `35f13d4b8c7285af305d9433e115f0861ca2a3689036e92ba676fc5a8daad0b2` |
| [native-contract-identity-after-write-001](../data/native-contract-identity-after-write-001/manifest.json) | 36/36 | 0 | `e0ec4ceb43a42c15dc6170cb066dec95c5541a748c284d10bd7787b77295d3de` |
| [native-contract-intent-before-status-control-001](../data/native-contract-intent-before-status-control-001/manifest.json) | 36/36 | 0 | `3a4c9c699c2201613c08b5bc2052ccd8717ee7b2d019332f9141cd190089c2f4` |
| [native-contract-intent-before-status-001](../data/native-contract-intent-before-status-001/manifest.json) | 36/36 | 0 | `ba53d2d5ada7a993d274dae6ed2eb728cc06ecd73996b94ddd4cf4ac65d16245` |
| [native-contract-intent-before-reserve-control-001](../data/native-contract-intent-before-reserve-control-001/manifest.json) | 36/36 | 0 | `57f0c3cef1a9c165ba6320d1ae1b917cfc361237bd1155f17b84f78d4bbde191` |
| [native-contract-intent-before-reserve-001](../data/native-contract-intent-before-reserve-001/manifest.json) | 36/36 | 0 | `e119311cb39c20ea16997eff26d324eed172da5eb984fb0031b6f4b124ab9753` |
| [native-contract-intent-after-reserve-control-001](../data/native-contract-intent-after-reserve-control-001/manifest.json) | 36/36 | 0 | `8fb9efbfcc0bea232ad48198160ec42011c6ddce21f6125708398c9d5fdea9fc` |
| [native-contract-intent-after-reserve-001](../data/native-contract-intent-after-reserve-001/manifest.json) | 36/36 | 1 | `f1c792ec0b901ddfd950a13eb35fdaae8181ee108fa7f5416e8a1f8d8e93a5a5` |
| [native-contract-intent-after-write-control-001](../data/native-contract-intent-after-write-control-001/manifest.json) | 36/36 | 0 | `6249a984b8cda3ff6338ecbdc14bee8ba4fd5dcac6490c46a30d92eb657afdc0` |
| [native-contract-intent-after-write-001](../data/native-contract-intent-after-write-001/manifest.json) | 36/36 | 0 | `670c8b19871072d7279698c19054f223dde24c3688eb03dfcf5ddfb32e3f91e4` |
| [native-contract-binding-before-status-control-001](../data/native-contract-binding-before-status-control-001/manifest.json) | 36/36 | 0 | `628f857118a27269ab66d103167bb3fb4ba18f24caadc9dfcea6a26d184c5023` |
| [native-contract-binding-before-status-001](../data/native-contract-binding-before-status-001/manifest.json) | 36/36 | 0 | `c5389f33ee75b136cffd7f1f6bb6a4f8bf812b530e896262a42d49a217f1204e` |
| [native-contract-binding-before-reserve-control-001](../data/native-contract-binding-before-reserve-control-001/manifest.json) | 36/36 | 0 | `9cc5c51d39570ad0724e1cf767833b0c1c3b972ce82da272f0718ef518ecad7f` |
| [native-contract-binding-before-reserve-001](../data/native-contract-binding-before-reserve-001/manifest.json) | 36/36 | 0 | `a0eef966eb962296cc9dbcd86c065e4fbc2633287947a2540236cfc47f0e476f` |
| [native-contract-binding-after-reserve-control-001](../data/native-contract-binding-after-reserve-control-001/manifest.json) | 36/36 | 0 | `922b2a9324666a55b6aa13adbf36eef283f597f71e9f9a70837892637aca718a` |
| [native-contract-binding-after-reserve-001](../data/native-contract-binding-after-reserve-001/manifest.json) | 36/36 | 1 | `81e3c18bdc91f00c7bc5a080ccbd89c9134d8e7d7842f21e07d4cbbc4a82afff` |
| [native-contract-binding-after-write-control-001](../data/native-contract-binding-after-write-control-001/manifest.json) | 36/36 | 0 | `3f3a0222066b2949a8c2e4f81089fbf5b76b9ca180cef531da87a4226df7203f` |
| [native-contract-binding-after-write-001](../data/native-contract-binding-after-write-001/manifest.json) | 36/36 | 0 | `d61283e43ee1e8c41c3abed6f31a2a6911a9b32c70c422e2554bd6d4590ba5ed` |

## 工程验证

新增10个测试方法，完整框架288项通过，覆盖全部40份证据、合同缺失、源码篡改、未知配置、伤害改写、Completion误声明与观察器失效。此前失败批和已知伤害均保留。

[工程验证037](engineering-validation-037.json)、[逐族索引016](mechanism-coverage-audit-016.md)、[复跑说明](../REPRODUCE.md)、[22份审核源码](../engineering-evidence/native-contract-sources-001/manifest.json)、[工具快照](../engineering-evidence/native-contract-tools-001/manifest.json)、[导出及进程复核](native-contract-final-review.json)。导出只包含封套白名单；私有状态和密钥未导出，已对本轮材料进行已知凭据匹配检查。
