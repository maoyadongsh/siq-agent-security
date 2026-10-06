# P04 同内容新导入与批准凭证身份绑定

日期：2026-10-06（Asia/Shanghai）。本报告为作者侧受控实测，不是独立第三方认证。

`lifecycle-attacks-004` 在前三批生命周期攻击基础上增加八项来源身份检查，总计 42/42 通过。新增部分使用相同 Skill 字节、不同本地导入目录与 import_id，在真实产品 HTTP 服务上执行。它证明本次批准凭证没有被另一个 Grant 接受，不代表远端 Git/HTTPS 发布者认证、同 UID 隔离或所有授权路径均已验证。

## 设计与正负对照

原 V2 候选仍处于待批准状态时，把其 SKILL.md 原样复制到新的测评目录，以新的 import_id 调用真实导入接口。两份文件 SHA256 与导入 artifact_digest 相同，但导入身份不同。新导入经正常权限创建接口生成另一个 Grant，再设置与原候选相同的文件/工具权限并处理其 overlap 条目。

随后为原候选签发尚未消费的批准 challenge，按如下顺序调用：

| 步骤 | 真实结果 | 证据解释 |
| --- | --- | --- |
| 新导入创建权限 | 201，新的 Grant 为 pending_approval | 相同字节不继承另一个候选的批准状态 |
| 将原 challenge_id 与 nonce 交给新 Grant 的 approve | 400，`grant: approval challenge grant_id mismatch` | 明确因 Grant 身份不符拒绝，非过期、已消费或错误 nonce |
| 立即读回新 Grant | 完整返回与攻击前相同，仍 pending_approval | 拒绝未偷偷改变该 Grant；前后文件摘要也相同 |
| 把同一 challenge_id 与 nonce 提交给原 Grant | 200，原候选 approved | 错误 Grant 尝试未消费凭证，正常流程仍可完成 |
| 使用新 Grant 准备安装更新 | 409，`skill_install_changed`；文件不变 | 新 Grant 仍须自身完成批准，原候选批准不跨身份生效 |

批准请求中的明文 nonce 不导出。测评器在脱敏前记录请求 nonce 与签发响应 nonce 的 SHA256，离线评分要求三者一致，且签发 → 跨 Grant 尝试 → 原候选成功的请求序号严格有序。还核对实际 approve 路径与响应中的 Grant ID，避免借用其他对象的成功或拒绝结果。摘要证明本批捕获的一致性；作者自持摘要不能认证独立执行者身份。

## 批次规模与证据

完整批次是一条有状态、有顺序依赖的旅程：74 次测评器 HTTP、3 次真实 Hermes CLI、12 次本地确定性模型请求、4 条签名工具回执。八项新增检查是管理 API/状态/文件效果检查，没有额外的原生工具调用；不能把 42 项检查或 74 次请求当作独立攻击样本。原生调用仍为一次正常读取及两次被拒的越权写入。

继承的其他检查包含候选扩权、导入副本完整性、计划完整性、卸载冲突、SIGKILL 后恢复、明确清理重试与旧请求保护新目录。其范围见[生命周期专项](lifecycle-attacks-report.md)。没有修改产品二进制，仍使用 nativefixturefix1 与固定 SHA256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`；宿主源码与 CLI 身份前后相同。

- [独立复核结果](lifecycle-attacks-004-verification.json)：42/42，退出 0。
- [原始脱敏 HTTP](../data/lifecycle-attacks-004/http.jsonl)、[评分](../data/lifecycle-attacks-004/score.json)、[冻结协议](../protocols/lifecycle-attacks-004-protocol/protocol.json)。
- [导出及资源核对](lifecycle-attacks-004-export-review.json)：已知凭据/私钥标记扫描无命中，三个原生 CLI 退出 0，两个 daemon 身份均不存在。
- [工程验证](engineering-validation-019.json)：126 项框架测试通过，Ruff 与 diff check 通过。

新增负向校准证明：过期拒绝不能代替 Grant 绑定拒绝；新的 nonce 不能冒充原凭证复用；接口拒绝不能掩盖新 Grant 被批准；不同内容不能冒充同字节身份实验。

## 复核与全新执行

离线复核锚点为 `ad6e706974dd8511a11ad71ac80079498fb14b33d2828b2eea748e5d646599f8`。使用 REPRODUCE.md 中配置的 Python：

```bash
$SIQ_EVAL_PY benchmarks/third-party/verify.py \
  third-party-evaluation/20261006/data/lifecycle-attacks-004 \
  --expected-manifest-sha256 ad6e706974dd8511a11ad71ac80079498fb14b33d2828b2eea748e5d646599f8

$SIQ_EVAL_PY benchmarks/third-party/lifecycle_attack_trial.py \
  --campaign third-party-evaluation/20261006 --run-id <全新ID> \
  --restart-mode sigkill --source-integrity --source-identity \
  --candidate-root third-party-evaluation/20261006/private/candidates/5470ab3780f2-nativefixturefix1
```

执行器在运行前冻结协议与源码，不覆盖已有批次；仅使用自有 HOME/profile、合成文件和本地确定性模型。未来还需远端来源替换、活动第三方 hook、独立撤权/派发竞态、服务断连及工具 pending 恢复等；这些未完成项继续记入台账。
