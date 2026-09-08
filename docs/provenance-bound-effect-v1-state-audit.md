# Provenance-Bound Effect V1 状态与签名审计记录

日期2026-09-08；起点`d001c4d`，审计源码`519cf2e`。新增生产集合/签名调用检索索引见[JSON](evidence/provenance-v1/state-signing-index-20260908.json)。索引排除测试、基准、验证脚本和重复内嵌资产；检索命中不代表审计通过。

## 已核读的状态边界

| 集合 | 实际边界与失败行为 | 源码 |
| --- | --- | --- |
| HTTP observer缓存 | 128条；持锁先清到期项，满时拒绝；scope/source字符串有长度限制 | `server/effect_http.go` |
| HTTP文件待采样缓存 | 128条；清过期项后检查；接管删除旧缓存，重新从签名记录恢复 | `server/file_observation_http.go` |
| Hermes来源引用缓存 | 2048条/5分钟；只缓存ID；失败重报移除旧引用；不靠淘汰活跃引用伪装采集成功 | `adapters/runtime/hermes-agentshield/__init__.py` |
| 来源图active/done | active由64层深度约束，done最多1024节点；4096边；每次解析独立生命周期 | `provenance/graph.go` |
| 来源参数resolved/seen | bindings/constraints最多1024，每参数引用最多32；调用内临时集合 | `provenance/matcher.go` |
| 签名Intent约束去重 | EffectRequirements最多128，ProvenanceConstraints最多1024，先验证数量后建集合 | `intent/validate.go` |
| Completion seenReq/seen/actions | requirements最多128、records最多8192；先检查长度；动作只保留本任务相关记录 | `completion/evaluate.go` |
| 历史效果wanted/found/approved/resolved/out | 输入最多8192；扫描全链但只保留wanted引用，不随全链历史无限增长；返回闭包只捕获本次结果 | `receipt/effect_history.go` |
| 效果和撤销磁盘记录 | EffectEvidence最多8192，Intent及全局撤销最多4096；不覆盖原签名记录 | `effectevidence/store.go`、`intent/store.go`、`intent/intent_revocation.go` |
| NetworkOracle事件列表 | 最多64，超过返回503；每请求body最多1MiB | `effectevidence/network_oracle.go` |

表中Go相对路径均在`apps/agentshield/internal/`下。容量证明还需结合各对应边界测试，不将条目数量当作安全得分。

## 请求范围的临时集合

`provenance/defaults.go`的seen来自签名显式约束及RuntimeAction的高影响路径；前者最多1024，后者随请求JSON大小增长。`runtimeaction/describe.go`遍历参数map/array，产生临时路径集合，不跨请求保留。生产Decide入口`server/server.go`用4MiB请求体上限约束来源，随后matcher拒绝超过1024个约束。

这一实现有请求范围的边界，**没有独立的描述器节点/深度预算**；不能把4MiB输入上限描述成固定内存或CPU上限。JSON深度、长路径重复构造和直接Go调用的成本仍需单独评估。暂不将这一项作为全范围G3最终通过证明。

## 签名复用核读

来源声明/issuer、上下文、全局撤销、效果记录、pending及恢复链均调用既有`signing.Key.SignCanonical`/`VerifyCanonical`；其实现仍由既有`canon.Marshal`生成规范字节。pending/recovery使用`canon.Decode`保留整数，避免JSON float转换改变签名字节；这不是另设签名算法。跨语言固定向量已覆盖来源/效果/上下文及新增恢复、全局撤销记录，详细命令见开发台账。

离线Python验证器的独立规范字节和Ed25519检查属于跨语言验收工具，不是生产签发端；不得以它签发运行时权限。完整G4验收仍需核读索引其余调用、旧版本双读与类型边界，不依靠“代码中没有直接ed25519.Sign”这一条搜索结果下结论。

## 后续审计任务

1. 对RuntimeAction参数遍历评估深度/节点/输出字节预算，不能通过截断丢失高影响参数后继续授权。
2. 核读完整生产diff的授权决策入口，确认任何模型/外部观察结果不能替代签名Authority（G5）。
3. 完成测试脚本和基准自身的资源预算审计，并与生产状态界限分别记录。
4. 最终验收索引保持未完成状态，继续逐项取证。


## 后续补强结果

本轮已加入`runtimeaction/budget.go`前置遍历预算：64层、8192节点、单指针1024字节、累计指针1MiB；Describe在超限时返回unknown/error及空资源，Engine三模式签名拒绝、Intent matcher拒绝。上文“没有独立描述器预算”为519cf2e审计时发现，现已修复；运行证据见开发台账。剩余全范围审计结论不因此自动变为通过。
