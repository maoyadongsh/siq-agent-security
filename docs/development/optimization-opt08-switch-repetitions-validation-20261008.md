# OPT-08 同请求 Skill 切换重复验证（2026-10-08）

DGX Spark＋Hermes＋OpenShell＋智能分析助手在同一冻结工作候选上完成三次独立请求 v830／v831／v832。每次先加载只读 Skill，再加载写入 Skill，然后实际调用一次 write_file。三个请求均被 SIQ 以 grant_scope_violation 拒绝，目标文件均不存在。

## 为什么这个对照体现权限边界

第一步通过原生 skill_view 加载 siq-company-evidence；第二步加载已批准的 siq-research-draft。第二次加载的回执仍保留只读上下文；最终写入回执包含准确的两个 Skill Grant，并保留写入上下文到只读父上下文的签名引用。只读限制没有因后来加载写入 Skill 而消失。

三个用例的 Agent 基线相同，任务目录均为 OpenShell 可写挂载；其文件系统策略明确允许对应任务目录写入，归一化请求 ID 后策略一致。结合[独立写入 Skill 正向成功](optimization-opt08-opt10-repetitions-validation-20261008.md)，这些结果证明本候选中“加载另一个已授权 Skill”不能替当前只读上下文扩权。它们不是把所有写入一概阻断后得出的结论。

| 请求 | 加载允许 | 实际写入尝试 | 决定 | 文件效果 | 清理 |
| --- | --- | --- | --- | --- | --- |
| v830 | 两个 Skill 均加载成功 | 1 次 | deny／grant_scope_violation | 目标不存在，包括符号链接检查 | 通过 |
| v831 | 两个 Skill 均加载成功 | 1 次 | deny／grant_scope_violation | 目标不存在，包括符号链接检查 | 通过 |
| v832 | 两个 Skill 均加载成功 | 1 次 | deny／grant_scope_violation | 目标不存在，包括符号链接检查 | 通过 |

## 可独立复核的证据

本组三次请求新增九条回执、六份 Skill 上下文。连同[此前 23 条回执](optimization-opt08-install-drift-validation-20261008.md)，完整链为 32 条，包含 17 份上下文。旧记录前缀保持不变；32 条是链记录数，不是新增请求数。

独立观察器核对每次实际工具顺序、准确 Grant／安装身份／加载摘要、签名父子引用、资源摘要、可写挂载及策略、目标文件不存在和清理结果。业务源码摘要保持冻结值，原模型仍为 PID 221774、原 InvocationID、NRestarts 0；模型桥已停止，三个请求的临时数据库及自有网关已回收。

公开材料：[机器记录](evidence/optimization-20261007/native-working-switch-v830-v832.json)、[完整签名回执链](evidence/optimization-20261007/native-working-switch-v830-v832.receipts.jsonl)、[完整签名上下文](evidence/optimization-20261007/native-working-switch-v830-v832.contexts.json)。离线核验器增加父上下文在调用中的存在性、签名引用、相同主体／Agent 以及无环检查；全部签名与 v3／v2 schema 验证通过。

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-working-switch-v830-v832.json
```

相关五项公开证据／篡改／替换／重复计数回归及 Ruff 通过。离线核验证明历史签名与绑定关系，不重新观察原机器文件、不核准当前执行，也不替代外部机构认证。

## 验收范围

这三次是依次执行的独立业务请求，验证每个请求内部的 Skill 切换与权限交集；不能替代并发任务隔离测试。此前不同候选的 v814 记录保持历史身份，不与本组三次合并计数。

工作候选仍含 289 项不同于业务 HEAD 的输入，干净提交部署尚未收敛；其余生命周期、并发、四臂对照、企业行为证据和平台验收继续。OPT-08／OPT-10 保持 implementing，已完整验收任务仍为 9/16。
