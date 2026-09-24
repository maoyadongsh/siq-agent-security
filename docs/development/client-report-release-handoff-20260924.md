# 报告工具客户端发行交接（2026-09-24）

本批完成新准备二进制的 DGX Spark 原生启动检查，并为正式打包增加已审阅源码清单校验。正式签发、签名安装、升级和回滚仍未执行；没有创建新提交或改变在线服务。

## 本机实际验证

Linux ARM64 二进制 SHA-256 为 `fd80fdb70eca6737016282f01a59a22c9991ab85d38a1a388053bf57b895b891`，与上一批四目标构建记录一致。使用既有 `skill_source_smoke.py`，随机 loopback 端口、独立临时状态完成：

- 未签名源码 bootstrap 在产生状态或暂存文件前拒绝。
- 自扫描 Skill 得到 `admit_with_conditions`。
- `start` 的状态查询、配对、控制台读取和正常停止。
- `init` → `serve` 的相同完整流程。

临时进程和状态由驱动正常清理，未注册用户服务或修改原实例。检查前逐文件确认当前 Skill 与隔离构建源码中的 Skill 一致。

原生报告里的 `source_sha` 是运行检查脚本的工作树 HEAD，**不是二进制源码声明**。二进制来源仍是 E163 `fd02384d6de5f96a849f9d04bbfbfaff38cf6148` 加上一批 11 文件补丁，通过二进制摘要和上一批构建记录关联；不能把二者混用。

## 防止漏发新报告工具

`package.py` 新参数 `--expected-source-inventory` 在固定提交导出后、npm/Go 构建前比较完整发行源码的路径、SHA-256、字节数及可执行标记。缺失、多出、内容不同、可执行标记不同均拒绝；默认历史调用方式不变。

本次已审阅清单包含 1,829 文件，范围严格为打包器 `SOURCE_PATHS`，没有把企业控制端或私有状态放进客户端包：

`var/flagship/client-report-release-handoff-20260924/reviewed-release-source-inventory.json`

清单 SHA-256：`6a65d84fdfff04152d98ae63bc4f3b620a9e7aadaca52c7ba5591afdd5f608dc`。

实际检查结果：隔离的已审阅源码匹配；对真实旧 E163 提交调用打包器被拒绝，没有执行构建或签名，没有创建发行目录。18 项发行工具单测通过，含旧内容、缺文件、多文件、模式变化、符号链接及打包失败顺序；修改的 Python 文件 Ruff 通过。同时修正打包脚本已有的可执行标记和显式 `check=False` 静态检查问题。

清单没有发行签名，须核对这里固定的摘要。它保证所选提交包含已审阅的发行源码，不能替代源码来源审查、官方签名或原生安装验收。

## 正式签发接续

先由维护者将已审阅的 11 文件增量纳入新的正式候选提交。此操作本批未执行；旧 E163 仍保持原样。新提交即使包含发行工具或文档等额外变更，导出的 `SOURCE_PATHS` 也必须与该清单完全一致，否则重新评审和验证，不能重生成清单来跳过差异。

已有受控签发环境只向打包进程注入原发行密钥。以下是后续命令模板，本批未执行，不能使用旧 E163 SHA：

```bash
cd /home/maoyd/siq/siq-agent-security
: "${SIQ_RELEASE_SOURCE_SHA:?请填入已审阅的新候选完整提交 SHA}"
printf '%s\n' '6a65d84fdfff04152d98ae63bc4f3b620a9e7aadaca52c7ba5591afdd5f608dc  var/flagship/client-report-release-handoff-20260924/reviewed-release-source-inventory.json' | sha256sum --check -
python3 scripts/release/package.py \
  --source-sha "$SIQ_RELEASE_SOURCE_SHA" \
  --expected-source-inventory var/flagship/client-report-release-handoff-20260924/reviewed-release-source-inventory.json \
  --version 0.4.0-rc.2 \
  --out-dir .tmp/client-report-signed-0.4.0-rc.2 \
  --sign
python3 scripts/release/verify.py \
  --release-dir .tmp/client-report-signed-0.4.0-rc.2 \
  --version 0.4.0-rc.2 \
  --source-sha "$SIQ_RELEASE_SOURCE_SHA" \
  --report .tmp/client-report-signed-0.4.0-rc.2-verification.json \
  --native-smoke
```

输出目录和报告必须不存在。随后执行旧版签名安装→升级→受支持回滚，沿用 [E163 交接的验收步骤](client-signing-handoff-e163.md#签发后剩余验收)，但发行版本和来源应使用本次新候选。没有原发行密钥时继续保持未签发，不能生成另一信任根替代。

本批[证据](../evidence/flagship-optimization-20260921/client-report-release-handoff-20260924.json)由 `var/flagship/client-report-release-handoff-20260924/candidate.json` 引用。其余生产权限、IAM、原模型和原生平台门禁仍按[收尾清单](flagship-closeout-current-20260924.md)执行。
