# DeepSeek 企业主线独立验收与修复

日期：2026-09-26。结论：**未通过完整主线交付验收；已完成首轮高风险实现检查和定向修复**。

## 1. 对象与证据范围

现场分支 `deepseek/enterprise-mainline-closeout-20260926`，HEAD
`2dd8b1f`，相对 `ebaaf3b` 的提交差异涉及 63 条路径。大量未提交、未跟踪的
并行成果仍在工作树；本轮不提交、不清理，不将整个工作树视为已审阅源码。

检查了分支差异清单、滚动交接/执行记录相关段落，以及新增周期枚举、内部拓扑/
失效投影、回滚授权改动和行为探针的关键实现；重点检查行为证据升级边界。
并非已逐行审阅全部 13,000 余行提交增量，也没有重跑全量门禁、30 个浏览器脚本。
旧日志、真实网关操作与历史授权为交付方记录，本轮未独立重演。

## 2. 真实缺陷与修复

先向 `test_enforcement_probe.py` 增加三个负例，在原实现上实际得到
**3 failed / 59 deselected**，未回退或覆盖共享工作树：

| 缺陷 | 修复前实际行为 | 修复 |
| --- | --- | --- |
| 目标未进入期望绑定 | 对 s1 读回，用 another-sandbox 的证据仍得到 enforcement_verified | 内部期望增加必填 target，CLI 与工具分别传入实际请求目标；逐字匹配，缺失/错配拒绝 |
| 拒绝臂只比较第一条 endpoint | 主方案三次拒绝中混入另一个 endpoint，仍被接受 | 两臂各自必须只有一个 endpoint，再按差分档检查相同/不同关系 |
| 通道忽略报告的 endpoint | 报告实际指向另一 endpoint，被搬运为请求 endpoint 而不报错 | 解析核对请求与报告 endpoint，精确顶层/attempt 字段、次数及 elapsed_ms 类型，拒绝布尔冒充整数 |

错误证据现在不会在上述路径升级，CLI 保留配置读回等级及固定拒绝原因。
没有新增权限、真实探测或 TTL，既有 wire 字段未增加；target 原本就在证据结构中，
本轮只将其纳入内部期望绑定。

脚本回归曾暴露一个测试夹具不一致：测试改用动态回环 endpoint，但模拟探针仍硬编码
api.example.com。修正替身按实际命令的 endpoint 返回报告，而非放宽产品校验；
错误 endpoint 的独立负例继续保留。

## 3. 本轮实际验证

工作目录 `apps/control-api`，均使用现有环境，不安装依赖：

```bash
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_enforcement_probe.py \
  app/tests/test_discovery_schedule_pending.py \
  app/tests/test_binding_invalidation_surface.py \
  app/tests/test_evidence_topology.py \
  app/tests/test_rollback_approval_readiness.py \
  app/tests/test_policy_flow.py
uv run --no-sync pytest -o addopts='' -q \
  ../../scripts/enterprise-experience/test_openshell_enforcement_probe.py
uv run --no-sync ruff check \
  app/adapters/openshell/enforcement_probe.py app/adapters/openshell/probe_channel.py \
  app/adapters/openshell/cli_backend.py app/tests/test_enforcement_probe.py \
  ../../scripts/enterprise-experience/openshell-enforcement-probe.py \
  ../../scripts/enterprise-experience/test_openshell_enforcement_probe.py
```

结果：后端六文件 **126 passed**；工具测试 **27 passed**；Ruff 与
`git diff --check` 通过。后端有既有 Starlette/httpx 弃用警告。
工具测试使用替身命令及隔离回环 socket，不执行真实 OpenShell upload/exec/set。
以上不等于全量、原生环境、真实身份或行为强制效果验收。

## 4. 主线剩余阻断及处置顺序

| 优先级 | 项目 | 验收判断/下一动作 |
| --- | --- | --- |
| P0 | 行为效果证明 | 修复结构与对象绑定仍不证明失败由策略导致。外部主机可达不能排除沙箱内 DNS/路由/服务故障；脚本路径/上传前摘要也不证明真正被治理的可执行文件身份。先设计独立可销毁目标、因果对照、边界身份及恢复方案，再申请真实操作许可 |
| P0 | 候选来源闭包 | 分支仍依赖未审查工作树内容；按实际逐路径依赖审阅、确认归属，不能因 63/63 清单存在就声称完整候选可独立复现 |
| P1 | R01 安装闭环 | 枚举接口已接线，原模块注释/交接旧表仍有“未接线”说法，已补记纠正；CLI 自动发现与独立确认仍缺，不是普通用户旅程已交付 |
| P1 | R02–R04 | 来源/内部只读拓扑与失效投影不是精确运行关系、版本绑定、独占/共享完整影响的实现；缺权威来源/业务标准时保持 unknown，不按文档完备关闭需求 |
| P1 | R05/R06 | 批量执行前端、独立回滚审批、完整版本引用及保留治理仍有明确缺口，不能全部归为真实资源等待 |
| P1 | 浏览器 5 项失败 | 交付记录尚报 25/30。需对实际失败脚本/截图复现归因；“文件由其他作者修改”不等于已证明因果，也不能替整个产品排除失败。本轮未复跑这些脚本 |
| 门槛 | 真实平台及发行 | AMD64/ARM64、身份、签发、发布、部署各自核验；不执行现有 canary 策略整段替换，不把字段并存当作 binary 运行期归因证明 |

只读日志通道受阻不证明写入型探针是唯一可能验证路径。D-9 的结构证据至多说明
读取到相应字段/形状，不能证明匹配顺序、组合语义或真实隔离效果。现有探针仍是
未获生产验收的内部机制；本轮没有把 capability 从 unknown 改为 supported。

## 5. 文件范围与交付口径

产品修复：`enforcement_probe.py`、`probe_channel.py`、`cli_backend.py`；
对应测试：`test_enforcement_probe.py`；工具及夹具：
`openshell-enforcement-probe.py`、`test_openshell_enforcement_probe.py`。
另纠正 `discovery_schedule_pending.py` 的已接线注释，滚动交接增加复核入口，
新增本记录。未修改共享安全策略、真实环境、并行作者其他成果。

**未提交、未推送、未签发、未部署。** 当前工作树包含本轮修复，旧 HEAD 的
preflight/制品摘要不再表示修复后的源码。后续冻结前应统一核验一次，不能反复
“提交账目→再核验→再提交账目”制造无限循环。

完整验收须继续完成第 4 节真实缺口及未覆盖审阅面；本记录不得作为全项目通过证明。
