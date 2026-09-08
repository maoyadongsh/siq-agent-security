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

## G4签名复用本地验收（基线693641d，2026-09-08）

相对起点d001c4d，internal/canon与internal/signing生产代码及测试无diff。核对新增Go生产签名/序列化调用及此前索引：Context、Provenance issuer/声明/撤销、Intent全局撤销、Effect内外封装、observer撤销、pending及recovery均走SignCanonical/VerifyCanonical/VerifyWithSchema，最终复用canon.Marshal。没有新增生产签名算法或另一个canonical编码器。

unsigned辅助函数只投影签名字段；JSON Marshal用于投影/磁盘编码，不是替代canonical签名字节。旧Effect Record投影保留既有float64语义，pending/recovery使用canon.Decode保留整数；不能互换两者或统一重签历史文档。Provenance payload摘要同样使用canon.Marshal，固定向量覆盖非ASCII/非BMP和整数。

运行Go1.26.6：canon/signing完整包无缓存race通过；provenance、effectevidence、intent匹配Vector/Signature/Tamper/CrossLanguage/AuthorityVerifies/ContextIntegrity测试通过。trustedcontext无直接测试文件，Context端到端测试位于intent与receipt，不把no test files计为测试通过；第一轮canon名称过滤未匹配，随后已完整执行。

G4据此记录为本地验收通过，范围是生产签名与规范化复用。Python离线验收工具的独立实现是跨语言验证端，不签发生产Authority；其资源预算和完整语义证明仍独立处理。G3/G5全范围审计没有因本项通过而自动关闭。

## G3/G5增量验收（源码20b85b1，生产基线693641d）

新增生产map按生命周期复核：固定taxonomy/unsigned字段投影不会随请求历史增长；HTTP observer/pending缓存均在持锁插入前检查128上限，finish只更新已存在项；Hermes来源/关联缓存2048并清TTL。图active/done、matcher和Completion临时map受64深度/1024节点/4096边、每参数32引用、128要求/8192记录约束。历史效果扫描只保留wanted动作集，不建立全链历史map。RuntimeAction输出集合先经过64层/8192节点/单指针1024字节/累计1MiB预算；默认provenance约束只由已验证最多1024显式约束及受预算descriptor生成。JSON解码字段map受HTTP/签名记录大小限制。G3本地验收通过。

此结论不是固定CPU/磁盘总量保证：完整回执扫描仍随历史长度增加；来源图按scope限制，不宣称所有scope磁盘总量有一个统一配额。调用内map和跨请求缓存区分处理，没有把无跨请求缓存等同于零内存风险。

G5生产授权流复核：cmd/agentshield/main.go只把ResolveStore、MatchParameters、GetContext接入引擎；Engine.Decide拒绝req.Intent，解析受信绑定并保留降级/撤销错误；Context/Provenance错误转为Authority invalid，ApplyMode先拒绝无效Authority，再处理普通policy。管理签发路由与decision report/select分权；Completion只读签名Intent和历史证据，没有回写binding/Grant或调用批准接口。新增工具/效果/来源数据不作为LLM最终授权输出消费，G5本地验收通过。

实际验证：Go1.26.6对provenance/runtimeaction/intent/effectevidence/receipt/server运行Capacity/Budget/Bounds/Boundaries/Concurrent/Recovery匹配测试，无缓存race全部通过。此前Authority/Provenance/Effect原始HTTP正负测试为权限边界提供补充。G3/G5均以生产调用边界为范围，不声称对任意不受信Go插件提供进程隔离。
