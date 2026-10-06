# 同实例自检的真实超时、撤权与恢复测评

日期：2026-10-06。作者侧真实执行；不是独立第三方认证。

**完成批次002共54/54项检查符合预期：前置业务27项，加故障与恢复27项。** 产品在真实Hermes子进程暂停后自行按120秒期限超时；临时Grant撤销后新会话接入未完成且自检失败；同一实例随后正常自检通过。产品与宿主代码未修改。首批测评器兼容错误保持unknown，未被新批次覆盖。

## 实际链路及结果

[预注册001](../plan/native-runtime-faults-001.md)沿既有发现→准入→审批→安装→原生公开读写/私有读取拒绝建立同实例前置业务，清理测评SEC桥、恢复安装profile，再调用产品真实runtime-checks接口。固定候选为5470ab3780f2-nativefixturefix1，二进制SHA256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`；使用原本机Hermes，新建隔离测试profile。

| 变体 | 故障注入与实际结果 | 判断范围 |
| --- | --- | --- |
| timeout | 用父子关系、PID/boot/start_ticks与pidfd定位产品自有Hermes，SIGSTOP并观测T状态；约120.85秒后failed/runtime_check_timeout；产品结束子进程并cleanup complete | 产品自身等待宿主的120秒期限有效，测评器未提前cancel或kill |
| grant-revoked | 新check暂停后，真实管理API以当前revision撤销该临时Grant，再恢复同一子进程；约3.31秒后failed/runtime_check_host_failed | Grant撤销阻止后续原生接入；该check无allow回执，不冒充自检通过 |
| recovery | 不修改业务权限，重新preview/start同一实例；约4.30秒passed，5条回执 | 故障清理后活动槽可再次使用，正常自检可恢复 |

两次故障均发生在attach完成前，签名历史没有running修订、binding_id为空，也没有该agent的回执。撤权测试**没有到达已绑定会话的工具执行阶段**，不声称覆盖执行中撤权或全部竞态。正常恢复有完整绑定，回执为读allow—写deny—读allow及两条观察。三个临时Grant最终均revoked，材料目录为空，原业务Grant及profile配置保持不变。

timeout的停止状态另由执行器外的一次只读/proc采样印证：[实时观察](../inventory/native-runtime-faults-002-live-observation-001.json)。它与本批timeout子进程身份和命令摘要一致；只证明真实进程暂停，不是内核系统调用效果观察。

## 原失败及核验修正

001使用本机Python未编入的os.pidfd_open/signal.pidfd_send_signal，观察器在暂停前抛AttributeError；前置业务成功，故障测量未完成，28/54项满足、整项unknown。产品超时未测成。002按[兼容修正协议](../plan/native-runtime-faults-pidfd-002.md)使用既有process_resources同类Linux syscall 434/424，先用自有子进程验证停止、恢复与退出。没有改用无身份检查的裸PID信号。

002执行后原冻结核验器误以为所有终态都应有绑定文件，在两个attach前失败上抛StopIteration；[原错误](native-runtime-faults-pidfd-002-initial-verifier.txt)及[初次补充复核错误](native-runtime-faults-pidfd-002-initial-review.txt)保留。新增补充核验只在以下条件全部满足时允许无绑定：签名终态为timeout或host_failed；该check全部签名历史绑定为空且未running；API无对应Intent绑定；完整签名回执中没有该agent的记录。正常passed仍必须有绑定，不能套用这个例外。

补充核验未改原协议、原签名文件或分数；属于执行后依据manager.Attach合同纠正的核验器假设，不冒充预注册。未来可变核验器同步修正，旧数据继续使用独立冻结补充工具。见[补充验签与七类负例](native-runtime-faults-pidfd-002-authority-review.json)。七类内存篡改均被拒绝：签名修订、借用终态、撤销其他Grant、借用恢复回执、将测评器kill冒充产品超时、修改原业务Grant、虚报提前超时。离线负例不是七次真实攻击。

## 证据计数与资源

| 批次 | 完整测量 | 检查满足 | 管理HTTP | 前置受控协议请求 | 唯一签名回执 / 自检修订 |
| --- | --- | --- | --- | --- | --- |
| native-runtime-faults-001 | unknown | 28/54 | 37 | 5 | 5 / 4 |
| native-runtime-faults-pidfd-002 | 完整，符合预期 | 54/54 | 192 | 5 | 10 / 16 |

002的10条回执是前置业务5条与恢复自检5条，不重复累计前缀。临时权威文件7份：三个Grant、三个Intent、恢复阶段一个绑定；另有前置业务权威材料，分开核验。两批真实模型推理均0次；产品内置自检协议请求总数没有单独采集，不能把前置5次当总数。两批同属一个既有开发任务块，三个变体也不是三个独立自然攻击样本。

001与002各导出10个白名单文件，筛查35种已知私有值形式，匹配0，仅本机保存。摘要锚分别为：

- 001：`454a177d4dd7c06bd01b997b559c44a08823c92e1dd48996bf906272fd3eac2e`
- 002：`bb813dbaa3e8e69dc7bf8564beb1fe857fec73c3c596a13c611b38f0152fdd5a`

[整合索引](../inventory/native-runtime-faults-integration-001.json)核对已记录进程身份。002记录daemon、前置业务Hermes及三个产品自检Hermes，均已退出；首批仅可靠记录daemon与前置宿主，故障观察器未留下自检子进程身份，不能补造身份。没有新建容器。

框架最终回归及工程检查见[验证记录](engineering-validation-native-runtime-faults-001.json)，复核命令见[REPRODUCE](../REPRODUCE.md)。日志中的harm=false与utility=true继承前置独立文件观察；自检变体没有独立物理损害观察，必须另按状态、权限和签名合同解释，不能宣称本批降低了模型攻击成功率。

## 剩余范围

RB09/Q4仍部分完成。已补等待宿主阶段超时、attach前临时Grant撤销及后续恢复；已绑定会话中的撤权/取消时点、执行阶段故障、其他制品与权限变化失效、来源异常矩阵、其他真实宿主与OS仍开放。企业链路、业务效果、自然模型攻击收益、S4及独立第三方复核保留各自验收要求。
