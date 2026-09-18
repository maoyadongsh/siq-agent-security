# A08：cause 字段已完整捕获，插桩行为 A 仍失败

本次在原生OpenClaw进程中加载明确的内存诊断插桩，以本地合成模型完成一次新身份的WSL2/Linux运行。已固定模块的内存变换发生1次；观察尝试1次、发出1次，sink_failed与diagnostic_failed均false。行为A仍fail，diagnostic_completed=true，cause_capture_complete=true。该诊断不是产品修复或无插桩正对照，也不用于倒推旧A04–A07的原因。

Node约16.646秒自然退出1；namespace约18.992秒，Windows主传输约21.331秒，各执行层及外层均保留exit1。Node/namespace未timeout或kill，已等待回收；provider socket/thread与decision socket收尾，Linux cleanup由guest明确读回确认；Windows stdin/传输完整且wait/dispose。没有从Windows退出码单独推断Linux清理。

两次本地provider请求实际工具均为read/write。第一次固定write响应发出，第二次请求包含相同tool_call_id的失败write回复；stdout工具摘要为calls=1、tools=[write]、failures=1，successfulToolNames为空。目标在运行前后和两次请求时均不存在，provider因效果未落盘拒绝第二次请求。Node meta.error实际包含本地400/HTML/fixture拒绝文字，不作为真实云端或CDN故障证据。native_tool_exchange_observed=false是完整成功消费谓词未达，不能抹去实际失败工具调用。

Node stderr中的一条cause帧444字节、一条status帧679字节均完整捕获，原字节与三层派生记录一致。status记录写入444/444字节并完成。公开字段保留如下：

| 字段 | 实际捕获 |
| --- | --- |
| code | present，ERR_ACCESS_DENIED |
| permission | present，空字符串，未截断 |
| resource | present，空字符串，未截断，classification=unmapped |
| name / syscall | absent，值null |
| stack | skipped_unverified_lazy_stack，未采集 |

permission/resource确为own primitive空字符串，不能改写为null、absent或“捕获被裁掉”。空字符串没有提供具体文件路径、权限类别或native FS API；本批没有识别这些值。cause关联强度仅为same_owned_process，unique_call_id_binding=false；工具回复中的相同tool_call_id只证明回复关联，不能把它移用于cause的唯一调用绑定。没有用跳过的stack补出API或祖先路径，也没有纳入尚未确认的Node源码归因。

Run盘点、WSL主传输、namespace、Node共8条原始流，只有长度/SHA和解码状态公开；加上Plan的inventory/transport四条，共12条记录。两条诊断帧是Node stderr中的子片段，不是额外进程流。WSL主stderr为132字节，driver使用UTF-8 replacement且decode_error=true；原字节完整，不能称为无损UTF-8，也不能混同1559字节的Node stderr。

20个冻结输入、6个执行payload身份一致；21项安装源码pin与Node额外身份在执行后保持，unshare另列。control、namespace哨兵/效果、父namespace/tmp元数据和Windows私有根ACL记录保持。namespace fixture效果一致不等于write目标落盘；write目标仍absent。复核只读取保留原件，没有重新执行WSL、宿主或访问安装目录；不把有限pins等同于全部依赖审计。

仓库上下文为clean b68199be84f4af6c1c434f736a67a3bc72f2b4dc，相对b303c6f92392f3a44c306d81ad7323c6291ef4f2仅21份文档证据变化。它不是OpenClaw包版本或SIQ执行身份；本页宿主用原运行固定的package.json/Node摘要标识，没有重跑--version。SIQ/server/gateway未启动、真实云端模型请求为0，B未运行；本批一次插桩诊断独立计数，不改原18行矩阵与分母，不关闭原生平台验收。

独立实际复核已完成，报告摘要b6360ac79de29bead53c221348f60e0651f87bd355bf3ac78e79994573025b23已列入来源。材料包含新A08实际身份，保留旧件；主任务已审阅公开白名单并完成初次秘密扫描；最终目录另作提交前扫描。公开材料的完成不改变行为 A 失败和 B 未运行。
