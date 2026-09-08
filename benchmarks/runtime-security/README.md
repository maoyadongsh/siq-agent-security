# Runtime Security Benchmark

本目录对应开发模板 §65–71。基准独立于检测规则单测，最终必须由真实运行时、签名回执及受控效果 oracle 产生结果；预期字段只用于比对，不能充当实际观测。

场景由 `scenario.schema.json` 约束：每个攻击场景指定正常对照 `pair_id`、攻击类别、任务和确定性 fixture 标识；至少20对及模板列出的全部攻击类别仍须落实到执行器。fixture 标识不能作为任意 shell 命令执行。

阶段语义：D0 语义接受、D1 不安全承诺、D2 动作尝试、D3 工具实际执行、D4 效果观测、D5 独立核实效果。阶段结果为 true/false/null；null 表示 not evaluated，不得改成 false。D0/D1 可来自注明人工来源的 fixture；D2–D5 必须来自实际运行记录。

D5 只有具有独立 observer 和可核验材料的样本才能计入分母。仅有 tool_report、无材料或未执行 oracle 的样本排除，并报告排除数。拒绝动作且独立 observer 完成检查、确认未产生目标效果，可以计入 D5 false；“拒绝”本身不能代替独立检查。

统计必须按攻击/正常对照及D0–D5分别报告，不能通过混合分母遮蔽误拒。性能数据来自真实阶段计时，输出P50/P95/P99，不使用整体请求耗时冒充内部阶段耗时，不设置虚构SLA。

当前仅开始合同与统计组件；尚无完整场景执行器、20对运行证据或CI门禁，不代表本工作包完成。

## 运行组件基准

```bash
python3 benchmarks/runtime-security/run.py --out /tmp/siq-runtime-benchmark.json
python3 -m unittest discover -s benchmarks/runtime-security -p 'test_*.py'
```

当前执行器复用实际 daemon 的准入、Grant challenge/approve/deploy、Intent V3、MCP HTTP 及来源 API，运行 MCP路径控制、来源缺失、内容替换、跨会话重放4类攻击及各自可信USER对照，停服后离线验证回执链。D2来自实际决策回执；目标工具不执行，因此D3–D5为null。报告保留二进制与runner摘要、场景摘要、源码基线及回执ID，内部阶段耗时缺失时保持null。源码基线不表示工作树干净。
