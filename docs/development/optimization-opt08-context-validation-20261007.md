# OPT-08 A：原生 Skill 上下文合同与签名组件

日期：2026-10-07。状态：A 阶段通过；OPT-08 仍在实施。

## 交付边界

已建立 [ADR-056](../adr/0056-native-skill-invocation-authority.md) 与 `skill-execution-context/v2` schema，新增 Go `InvocationContext` 和独立跨语言签名样例。v2 区分 Agent baseline 与 Skill Grant，绑定原生任务、精确安装、加载文件摘要、运行制品摘要及父上下文签名。租约最多一小时，Agent ID 必须匹配实例派生身份，父上下文不能自引用。

当前只完成文档结构和签名校验。`VerifySignature` 明确不校验当前有效期、撤销、真实安装、Grant 生命周期、父链或调用授权。未新增签发 API，未将 v2 接入决策引擎；v1 的签名、单 Grant 约束和读取器保持不变。不能据此宣称日常多 Skill 自动管控已完成。

## 实际链路发现

现行 SEC v1 的实例、会话和 Skill Grant 必须相同，Engine 也检查 Intent 与 SEC Grant 一致。历史业务测评通过手工选定 Skill 的同步器满足该条件；不能直接移除比较来支持多 Skill。

本批从当前候选镜像只读提取真实 `skills_tool.py` 与 `plugins.py`，固定镜像与源码摘要见 [来源记录](evidence/optimization-20261007/native-skill-loader-source.json)。使用缓存镜像、`--pull=never --network=none --read-only`，不加载业务目录或凭据，不启动模型。提取源码仅保留在忽略运行目录。

实际 `skill_view` 包装器的重复读取缓存可提前返回，成功后的使用统计位于捕获异常并忽略的分支。现有生命周期遥测不是安全门禁。后续可信加载接入需覆盖缓存命中、失败、嵌套/切换与并发路径，不能仅订阅成功统计。

业务仓库已有大量未提交改动，本批没有修改该仓库；只对四个相关集成文件记录来源摘要，保留在 `var/optimization-20261007/opt08-discovery-baseline.json`。后续跨仓改动将逐文件单独核对。

## 验证

| 范围 | 结果 |
| --- | --- |
| Go 新组件 | 12 类结构反例、8 类签名篡改、确定性跨语言样例及 v1/v2 隔离检查通过 |
| Python 独立读取 | 16 项通过：JSON Schema、独立 Ed25519 验签、缺字段/未知字段、合法形状篡改拒绝 |
| 既有 SEC | `go test -race ./internal/skillcontext` 通过，包含原 v1 签发、撤销、活体依赖及新 v2 文档组件 |
| Go 仓库 | `go vet ./...`、`go test ./...` 通过，44 个有测试包、10 个无测试包 |
| 构建 | linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标通过；不作为原生平台运行证据 |

日志：`var/optimization-20261007/opt08-context-contract.log`、`opt08-context-race.log`、`opt08-context-vet.log`、`opt08-context-go-all.log`。本批未改变 Python 产品路由，因此没有重复运行 API 全量；最后一次 API 全量仍是 OPT-07 的独立记录。

## 下一阶段

按照 ADR 的 B/C 阶段实现独立持久上下文、精确调用绑定、父链约束与实时双 Grant 交集，先完成失败关闭和恢复验证，再接入固定业务镜像与日常入口。签名文档、上下文存在、实际调用获准和外部效果必须分别证明。
