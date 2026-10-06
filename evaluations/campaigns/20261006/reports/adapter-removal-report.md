# P05 适配器整体卸载、配置冲突与活动插件保留

日期：2026-10-06（Asia/Shanghai）。作者侧可复核实测，独立第三方执行与摘要保管仍待完成。

`native-adapter-removal-001` 完成 33/33 项独立检查，其中 11 项新增适配器整体卸载检查。完整旅程包括正常安装、更新、受管 Skill 卸载、适配器卸载与卸载后的真实宿主行为。它是一条有状态的旅程，不是 33 个独立攻击样本。

本批 69 条测评器 HTTP 观察、4 次真实 Hermes CLI、16 次 loopback 确定性模型请求、5 条签名链记录。全部 CLI 退出 0，没有付费模型调用、产品源码修改或用户日常配置变更。使用本机 Linux/aarch64 Hermes 与固定 nativefixturefix1，产品 SHA256 为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。宿主源码、CLI/解释器身份前后相同；新增配置采集依赖 PyYAML 6.0.3，版本已记入冻结协议。

## 实际执行与结果

| 操作 | 直接观察 | 结论 |
| --- | --- | --- |
| 正常生命周期前启用第三方插件 | 良性 `third-party-observer` 在 V1、V2、Skill 卸载后真实执行 | 沿用前批活动插件正对照 |
| Skill 已卸载后，重新启动本批 daemon | 同状态、同端口、新进程身份；管理配对正常 | 不改变历史安装/卸载证据 |
| 在 SIQ 插件目录加入未知用户文件 | `user-note.txt` 有独立摘要 | 不是 SIQ 归属文件，不应整目录删除 |
| 预览适配器卸载 | 200，配置及采集文件不变 | 预览不直接卸载 |
| 预览后追加用户配置，再提交旧计划 | 409，文件及配置与提交前一致 | 拒绝使用失效预览覆盖新的用户配置 |
| 重新预览，再明确卸载 | 200，四个归属文件被删除 | 删除插件 manifest、代码、配置以及受管 helper |
| 核对保留对象 | 未知文件、原始 `.orig` 备份摘要不变；新增配置及其他插件配置语义保留 | 卸载范围限于有归属对象 |
| 查询运行时身份 | 当前实例身份为 revoked | 卸载没有重新激活身份 |
| 重放已成功卸载请求 | 200，采集文件与配置不变 | 本次重放未重复改写文件 |
| 启动新的真实 Hermes CLI | 第三方 hook 再次执行，正常读取返回本批随机标记；无该调用的新 SIQ 回执 | 明确卸载后 SIQ 门禁退出，宿主保持可用 |

SIQ 移除的四个文件为：`plugins/siq-agent-security/plugin.yaml`、`__init__.py`、`config.json` 与 `bin/hermes-skills-install`。由于保留未知文件，SIQ 插件目录仍可存在，这不代表归属文件删除失败。原始配置备份按合同保留。

配置比较按语义进行：排除宿主自动生成的 `_config_version`、SIQ 自己的 enabled/disabled 注册与 allow_tool_override 字段，保留和比较其他字段及其他插件条目。原生 CLI 会规范化 YAML，因此不把整个配置的字节相等作为恢复条件；备份和未知文件仍按字节摘要核对。

## 授权与归因边界

旧计划提交返回 409 的同时，响应明确说明 `runtime_identity_revoked: true`、`recovery_required: false`：产品先停用实例授权，配置变化使文件移除未继续。该行为符合卸载路径“撤权优先”的合同。不能把拒绝后的文件未变扩大为“所有授权状态都未变”，也不能声称重新预览恢复了旧授权。

本批开始适配器卸载时，前序受管 Skill 卸载已撤销其 Grant。运行时身份 revoked 有明确读回，但旧凭据拒绝不能单独归因给本次适配器卸载。独立撤权/派发竞态仍是后续工作。

卸载后原生读取成功是用户明确关闭 SIQ 接入后的预期行为，不计作攻击成功、防护绕过或仍受保护的读取。第三方 hook 保留只覆盖本次良性 pre-LLM 插件，未代表恶意插件隔离或所有 hook 排序/冲突。

五条验签记录包括 V1/V2 读取的四条 decision/observation，以及重启后补入的一条先前 Skill 卸载后拒绝的 pending 记录。后者缺少 tool_call_id/record_type，不能把它算成适配器卸载后的新在线决策；最终未接入 SIQ 的读取没有新增 SIQ 回执。

## 证据与复现

- [独立复核](native-adapter-removal-001-verification.json)：33/33、退出 0。
- [HTTP 与配置/文件效果](../data/native-adapter-removal-001/http.jsonl)、[第三方插件执行记录](../data/native-adapter-removal-001/hook-events.jsonl)、[最终配置投影](../data/native-adapter-removal-001/adapter-final.json)。
- [导出与资源核对](native-adapter-removal-001-export-review.json)：已知凭据及私钥标记扫描无命中；两个 owned daemon 身份均已不存在。
- [工程验证](engineering-validation-021.json)：142 项框架测试通过；Ruff 与 diff check 通过。

离线验证绑定两个提交到各自真实预览的 plan_id、digest、runtime identity 和 instance，并验证最终投影与原始采集一致。负向测试覆盖误删未知文件/用户配置/其他插件/备份、只有插件文件但未执行、出现新的 SIQ 回执及借用其他预览。

```bash
$SIQ_EVAL_PY benchmarks/third-party/verify.py \
  third-party-evaluation/20261006/data/native-adapter-removal-001 \
  --expected-manifest-sha256 bae7192c279ba2a55e71508133c46a9e9522e47780646ee4e39db6598c0ddfed

$SIQ_EVAL_PY benchmarks/third-party/native_lifecycle_trial.py \
  --campaign third-party-evaluation/20261006 --run-id <全新ID> \
  --active-hook --adapter-removal \
  --candidate-root third-party-evaluation/20261006/private/candidates/5470ab3780f2-nativefixturefix1
```

继续待测：适配器事务中断及恢复、更多第三方 hook/配置冲突、恶意插件、独立撤权竞态、网络效果、审批/工具 pending、磁盘/发布故障和其他宿主/OS/后端矩阵。材料仅落本机，未上传或发布。
