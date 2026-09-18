# O04/O00 复核修复与本机验证（2026-09-15）

本批保留 GLM 未提交成果，完成本机可执行的修复、原生服务 HTTP 验证和 O04 增量性能对照。工作分支 `kimi/personal-v4-r01-20260914`，父提交 `6e34f3ad82033b0b5ffe49cd82bc042c84414429`；全部修改仅落盘，未提交、未推送、未合并、未发布。

## 1. 复核发现与修复

| 问题 | 修复与验证 |
| --- | --- |
| 新增证据字段未替代编译器旧布尔判断 | 新增 `configuration_capabilities`；动态网络、模式和路由要求显式配置能力。旧布尔或历史 supported 行单独不能批准编译。历史记录附 documented 与适用范围。真实执行仍需 O01/O02 读回与授权。 |
| Go/Python status 判定不同 | 共享 11 条协议向量：首个非空行严格为 Server Status，且恰好一个符合 ASCII 规则的 Gateway 名；重复、空白名、非 ASCII、无关前缀均拒绝。仅确认协议形状，不声称加密身份认证。 |
| 间接配置变化可复用缓存 | PATH/env.sh 不复用目标相关缓存；显式配置绑定 TLS 模式和 CLI 文件信息；探测前后配置变化拒绝；刷新失败清空历史成功缓存。已退役 Docker 回退保持保守关闭，但不当作当前版本或能力证据。 |
| doctor 没有目标读回路径，状态只停留在握手 | 新增 `openshell doctor --target <name>` 和已鉴权 `GET /v1/openshell/doctor?target=<name>`。要求显式 CLI/endpoint 绑定；只读 revision 与全策略 digest，失败/漂移降级，不产生行为验证。 |
| 前端只呈现旧 L3 标签 | 显示协议/读回/失败等状态；每秒检查有效期，过期提示重新检查。当前无 behavior_verified 生产者，不能显示为已验证保护。已重建本地 embed。 |
| RSS 不可得时数值 0 容易被当作测量结果 | 输出格式提升为 `agentshield.perf_baseline.v2`；OS RSS 不可得返回 null/unavailable；Sys 仍单独命名。同步门禁、文档及序列化回归。旧 v1 证据不改写。 |
| D 超时路径稳定贴近 301ms，超过冻结预算 | Go 排空等待从固定 200ms 改为 min(200ms, timeout)。100ms 探针的故障返回约 201ms；未修改输出总限额、错误脱敏、进程停止范围和原预算。 |
| 原生 HTTP 验证被错误归为依赖真实 OpenShell | 新增真正 loopback TCP HTTP 旅程、授权前拒绝、准入/确认/部署、允许、撤销后拒绝及回执链验证；OpenShell/Docker Runner 调用数为零。 |
| 禁止 reset 被当作无法取得对照的原因 | 使用独立临时 git archive，只注入同一测试文件；不复制候选生产代码，不修改活动工作树。冻结配置、源码/测试/二进制摘要、轮次、样本及预算后测量。 |

相关合同：[capability evidence v3](../../../../packages/contracts/openshell-capability-evidence.v3.md)。
另修正了规格遗留的 Active-only 描述：现有两语言解析器和共享向量都接受规范 Active 或 Version；同时出现必须相等。本批没有更改 revision 解析行为。

## 2. 实测结果

### 超时和组件路径

[新 A–E 原始数据与报告](../openshell-o04-perf-20260915-070714/report.json)使用原来的预算、轮次和样本量，无剔除。全部预算通过。

| 指标 | GLM 原始测量 | 本批测量 |
| --- | ---: | ---: |
| D timeout p95，180 样本 | 301.0ms | 200.886ms |
| D timeout max | 301.4ms | 201.261ms |
| 冻结预算 | p95≤300ms、max≤500ms | 不变 |

[原失败证据](../openshell-o04-perf-20260915-062001/report.json)保留，不能用新结果覆盖原始未达标记录。

### 原生 HTTP 增量对照

[冻结协议](../openshell-o04-http-review-20260915-070639/protocol.json)、[原始样本与资源](../openshell-o04-http-review-20260915-070639/samples.json)、[结果](../openshell-o04-http-review-20260915-070639/report.json)。

每版本 3 轮，每轮允许与撤销后拒绝各 200 个计时样本，各 5 次预热；顺序 before/after、after/before、before/after。测量期间不并行运行本批测试或构建；两套测试二进制预先构建。统计使用最近邻秩百分位，不做离群剔除。

| HTTP 指标 | before p95 | after p95 | 变化 | 预设增幅≤10% |
| --- | ---: | ---: | ---: | --- |
| 允许 | 8.983741ms | 8.997900ms | +0.16% | 通过 |
| 撤销后拒绝 | 8.929005ms | 8.700955ms | −2.55% | 通过 |

候选每轮测量窗口 CPU 为 0.60–0.61s、末尾 OS RSS 约 22.6–23.2MiB，write_bytes 增量均为 4,005,888 字节。窗口包括两阶段、预热和 revoke，不能视为单次请求开销。每轮共 422 个本机 HTTP 请求；每组 400 个计时决策均符合预期，且 OpenShell/Docker Runner 调用数为 0。这不证明任意真实工作负载误拒率为 0，也不等价 OS 进程树测量。

对照基线是 **O01–O03 已完成、O04 尚未进入的 6e34f3a**。这是 O04 增量回归对照，不能标记为整个轻量化方案改造前 B0。源码在测量前后未变；源摘要、测试文件摘要和二进制摘要均已归档。

## 3. 验证

回归清单与四目标构建摘要见本目录 checks.json、cross-builds.json。覆盖 Go 全量/vet/race、Python 应用 lint 与全量、Web 测试与本地构建、性能门禁、新增安全负向及共享向量。生成器在临时文件重新生成的 6 条编译向量与历史冻结文件完全一致，未重写旧 fixture。

扩展执行 `ruff check .` 发现既有 migrations 导入规范问题；本批要求的 `ruff check app` 以及修改的生成器单独检查通过。不把应用目录 lint 通过表述为整个仓库所有 Python 路径通过。

## 4. 证据与复跑

```bash
# 仓库根目录；性能命令顺序运行，期间不运行构建或全量测试
python3 scripts/personal-experience/openshell-o04-http-comparison.py
python3 scripts/personal-experience/openshell-o04-perf-protocol.py
python3 scripts/check_perf_baseline_harness.py

cd apps/agentshield
go test ./internal/openshell ./internal/server ./internal/perfbaseline
go vet ./...
go test ./...
go test -race ./internal/openshell ./internal/server
```

每次性能 runner 创建新证据目录。HTTP runner 不执行 reset、clean、checkout 或网关启动，只使用临时 archive、隔离状态和 loopback HTTP。它不执行被准入 Skill 的代码，也不发送实际模型/外部工具请求。

## 5. 未完成边界

- 本批没有对真实 OpenShell 后端、已安装 daemon 或宿主智能体运行旅程做新验收；B2/B3 与 O05 保留待验证，不启动或修改现有网关。
- 完整优化方案的 pre-O01 B0 尚需选择等价基线和接口，当前 O04 增量对照不能代替。
- Windows/macOS 实机、Linux WorkBuddy 接入保持协作者既定任务；交叉构建不等价实机通过。
- 性能数据来自开发机、fixture 请求与指定样本量，不是生产 SLA；长期误拒率、进程树、真实后端资源与网络开销未测。
- 本批没有执行发布、部署或修改团队管理范围。

## 6. 接续顺序

1. 对本批源码和证据进行提交审查；当前是可复核的本机阶段成果，不能标记 O00/O04 全部实机验收完成。
2. 用明确归属的隔离真实 OpenShell 实例补新候选 B2/B3、目标读回与行为证据，避免把旧版本证据套在新二进制上。
3. 明确 pre-O01 的等价基线后补完整 B1−B0；继续收集 Win/mac 与 WorkBuddy 真实环境结果。
4. 达到总体任务书依赖后推进 O05；不因组件性能通过而直接开放会话执行或提前完成团队阶段。
