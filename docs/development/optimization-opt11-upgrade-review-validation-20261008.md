# OPT-11 企业升级前核验与确认绑定

日期：2026-10-08。DGX Spark / Linux arm64。分支 `codex/security-optimization-20261007`。
本批基线 `7c4b11d9`；源码、构建和原始日志摘要见
[机器可读证据](evidence/optimization-20261007/enterprise-upgrade-review.json)。

## 本批结果

新增 `review-enterprise-upgrade` 只读入口，为后续升级事务形成完整且可重新核对的意图。
不修改现有计划/服务、不创建任务锁、不执行采集器、不调用控制面或 systemd。
**OPT-11 仍为 implementing，总体 11/16（68.75%）**；本批不是完整升级验收。

依据 [ADR-061](../adr/0061-enterprise-service-upgrade.md)、
[review v1 合同](../../packages/contracts/enterprise-upgrade-review.v1.md)与
[JSON Schema](../../packages/contracts/enterprise-upgrade-review.v1.schema.json)。

## 核验内容

| 对象 | 必须满足的条件 |
| --- | --- |
| 设备 | 私密目录、无链接路径、受限权限与单链接状态文件；绑定准确状态路径和原始字节 SHA-256 |
| 旧安装 | 已确认计划摘要、原目标与架构一致、旧暂存发布签名及实际制品复验；旧安装窗口可已过期 |
| 新安装 | 当前有效计划、相同租户/环境/origin/本机架构/user 模式，新暂存独立验签，不接收自报可信 |
| 服务配置 | 精确匹配由旧暂存和原状态目录生成的 unit；自定义配置、可写父目录、链接/漂移明确拒绝 |
| 确认绑定 | 完整新旧计划、暂存位置、状态/单元路径及摘要一起规范化；中文路径 Go/Python 摘要一致 |
| 复核 | 两个 stage 再验，状态/新计划/旧 unit 再读；过期、取消或变化后不输出通过文档 |
| 输出 | 无设备 token/签名 seed；标记 not_checked 服务状态、未验证能力、未安装、未授业务权限 |

输出是审阅材料，不是审批凭据。后续执行入口必须重新构造相同 intent，再检查用户确认摘要、
任务排他锁与服务停止状态；不能直接接受外部 JSON 的 `publisher_signature_verified` 字段。
输出写入中断可留下截断字节，返回失败；消费者必须要求完整文档及成功退出，不解释局部字段。

## 验证

- Edge 本批全量：**226 个顶层测试通过、2 项既有条件跳过**；包含子测试为 720 个通过事件。
  跳过为 `TestInstallPlanWireParity`、`TestSkillAncestryNativeExport`，未计通过。
- 新升级核验 6 个顶层测试、31 个含子测试事件通过，定向 race 同样通过；这些包含在全量内。
  反例覆盖目标/租户/架构/模式、旧确认摘要、过期/未来新计划、自定义 unit、可写目录/文件、
  符号链接、未知状态字段、计划损坏、核验中状态/计划/unit 漂移、期限跨越、取消与签名拒绝。
- Go 实际输出的合成样例回灌 Python：**11 项合同检查通过**，含独立规范化 SHA-256、
  中文范围、字段/嵌套计划约束及不得把已安装/已停服务/已验证能力写成 true 的负向。
- `go vet`、受影响 Go 格式、Python Ruff 通过；Linux arm64/amd64、macOS arm64、Windows amd64
  四目标构建通过。后面三个不是本机原生运行验收；非 Linux 命令明确 unsupported。
- 实际本机 ARM64 CLI：帮助入口正常；合成已登记状态、准确旧 unit、当前新计划与伪造签名暂存
  被拒绝，stdout 无审阅结果、安装文件字节不变、无 tasks.lock、无私密 token 输出。

全量 Go 使用明确 overlay 仅排除预先存在、属于其他工作的未跟踪
`edge/agent/crash_recovery_test.go`，没有修改或删除该文件。`go list` 核实本批新测试在内、
该无关测试不在内。全量不是对未提交协作成果的验收。

## 证据性质与首次 CLI 失败

成功 review 的组件测试使用明确的内部验签替身；它验证编排、字节/上下文绑定和只读后果，
不能证明正式发布签名。产品 CLI 始终调用固定公钥 VerifyStagedBundle，无替换公钥、跳过验签
或测试模式参数。独立原生 CLI 负向使用真实生产验签入口，未运行正式签名正向。

`edge/agent/testdata/enterprise-upgrade-review.synthetic.json` 是上述组件样例；其中
`publisher_signature_verified=true` 为合成测试值，不是对某个真实发行的通过声明。
样例中的临时路径已随测试清理，不可直接用于升级。

首次原生 CLI 测试先因测试脚本创建的中间配置目录组可写而拒绝，尚未走到签名拒绝。
仅将一次性测试目录明确设为 0700 后完成预期签名负向，生产权限检查没有放宽。
此前的源码候选、样例和证据均未改写；本批原始日志与构建位于
`var/optimization-20261007/opt11-upgrade-review-{logs,builds}/`。

## 后续必须完成

1. 实现受任务锁和停止状态约束的升级切换、持久恢复日志及正常运行入口的中间态拒绝。
2. 完成实际中断后的继续/恢复旧安装、并发与身份漂移负向，保持设备身份和执行/周期确认历史。
3. 获得有效企业签名制品，在真实服务管理器和独立设备状态下验收安装、合法升级、旧设备迁移。
4. 完整变更提交后重新冻结最终候选。前批 a9a8e91e 的两份未签名候选不含本入口，继续保留为
   当时的制品预检记录，不冒充最新完整企业包。

未安装服务、未停止日常设备、未调用模型或改变业务权限；未签发、发布或推送远端。
