# Hermes Windows 原生受管授权实跑证据

2026-09-18 的 r6 在 Windows 原生 Hermes 宿主上完成 B01–B05，控制器退出码 0，耗时 233.902 秒。模型由受控合成 provider 提供，没有付费模型调用、桌面交互或产品 runtime-check v5 验收。

候选为 `72140795963244d293232c905a34ef00312b8253`，运行前记录 `source_dirty=false`；二进制 SHA-256 为 `b96cb374993811d6940ee9be2a8e721b14a0c89a984952d71134242b85401d7d`。本批并非随后开发提交的原生验证。完整控制器与 14 项固定输入摘要见 [source-and-commands.json](source-and-commands.json)。记录中的生产钩子预算为 5 秒，命令没有覆盖此预算。

| 用例 | 真实结果 | 本用例回执 |
| --- | --- | --- |
| B01 | 授权文件写入 37 字节并读回 | 2 decision + 2 observation |
| B02 | 越界写被 SIQ 以 grant_scope_violation 拒绝，无目标文件 | 1 deny decision |
| B03 | 停止自有 SIQ 后，新原生进程 enrollment 失败关闭，无写入 | 0 decision；pending 拒绝 |
| B04 | 恢复 SIQ 后，有效授权文件再次写入 37 字节并读回 | 2 decision + 2 observation |
| B05 | 撤销身份后，新原生进程 enrollment 拒绝，无写入 | 0 decision；pending 拒绝 |

[cases.json](cases.json) 保留每步文件存在性、相对路径、字节数、SHA-256、前后快照和回执安全字段。两个成功文件 SHA-256 均为 `372424085826122c24485f32b06dd823da25d04b5c7b246db8d1efbd47bc4ab9`。控制器 guard 允许这些测试目标，且另行拒绝了附带的子进程尝试；不能把 guard 拒绝冒充 SIQ 越权裁决。B02 有精确的 SIQ 拒绝回执，B03/B05 的拒绝发生在 enrollment 阶段，不能描述为执行了 decide。

独立代理对保留原件进行离线核验，r3 退出 0：1355 个源码文件的聚合摘要、14 个固定输入、10 条回执的哈希链/Ed25519 签名及 checkpoint、4 个 Grant 修订、identity/撤销、Intent v4 与 Binding v2 以及副作用相互一致。不同 Authority 文档共 13 份，验签调用 17 次（包含重复引用），不能按 17 份不同文档计数。详情见 [independent-verification.json](independent-verification.json)。这是对同批原件的独立核验，没有第二次独立启动宿主。核验器 r1/r2 自身对 deployed 状态及 HTTP 方法筛选的假设错误保留为失败记录，不归为产品失败。

本批可支持既有台账 `P02-HM-A04-01`、`P02-HM-A04-02`、`P02-HM-A05-01` 三行。`P02-HM-A05-04` 仅部分支持：B04 是有效身份恢复后成功，B05 才发生撤销，**没有验证撤销后再重启服务的持续拒绝**。本归档不修改固定 303 项台账，不表示整个项目或三个宿主全部验收完成。

[prior-attempts.json](prior-attempts.json) 保留同候选 r4/r5 的退出 1、原日志摘要、不同控制器摘要和定位说明。r4 的 Windows subprocess 审计参数形状与 guard 假设不符；r5 已出现真实 SIQ 拒绝，但旧控制器条件只接受 blocked／instance session，漏掉正常的 denied 文案；该缺口与大小写无关。两次旧结果均保持失败，不追改成通过。

[cleanup.json](cleanup.json) 记录 10 个自有 Job Object 已关闭及隔离适配器已卸载；私有证据仍保留。部分 daemon 在 Close 前仍有活动进程，字段明确标为关闭前计数，不能读成关闭后仍在运行。没有注销、重启、睡眠或修改日常宿主配置。

公开材料采用字段白名单，不复制 Authority、凭据、配置、provider 全文、原始 HTTP、带私有路径的签名对象、用户目录、SID 或会话标识。42 份独立核验输入以 [private-inputs-sha256.json](private-inputs-sha256.json) 映射到私有原件摘要；状态对象名使用角色别名，并保留原私有清单相对定位字符串的摘要。核验清单在核验后采集，这一点未改称运行前固定。核验器只在私有内存中由测试身份派生验签公钥，没有新签名或公开秘密。

公开 JSON 是投影，**不具备原始签名对象的可验签性**；Ed25519 通过结论来自独立核验保留的原件。另保留不含本机路径或秘密常量的 [independent-verifier.py](independent-verifier.py) 原脚本供代码审阅；它需要私有原件及 cryptography 依赖，不能仅用公开投影重现验签，也没有在归档阶段执行。[provenance.json](provenance.json) 区分原始文件摘要与公开投影，`SHA256SUMS.txt` 仅校验本目录公开文件，不把摘要清单冒充可信签名。归档只读原证据并写新目录，没有重跑宿主、模型、测试或编译。
