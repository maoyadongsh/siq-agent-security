# PR #76 合并复核（2026-09-18）

审阅基线 main `bb364015f745316497f0d654ee9746b5287035c0`；原提交 `a792a0291422bede4c9232bad9b6f328669ee13b`。本次仅测试可移植性修正，不改变产品引擎、授权时钟和回执。

修正允许已执行短阶段返回非负耗时，保留样本数、未执行阶段无样本及安全决定等价断言。可测量的 IntentLookup 至少等待 2ms，独立排除错误地使用冻结授权时钟。Linux 本机完整 receipt 包、race、vet 和 Windows amd64 测试二进制交叉编译均退出0；不代表新增 Windows 实机验收。用 Go overlay 临时替换计时器为授权时钟，两分支均按预期失败（go test退出1），源码文件未修改。

## 公开字节与历史原始摘要

原 verification.json 字段名为 private_log_sha256。直接比较公开日志时四项不匹配：对当前公开 LF 字节转换为 CRLF 后，恰好匹配其历史摘要；mutant.log 原样直接匹配。这里只验证确定性的字节变换关系，未取得作者本机私有原件，不宣称重验原始 Windows 运行。原清单和公开日志保持不变，下表补充可直接核验的公开文件身份。

路径根：`docs/evidence/personal-experience/windows-sunbo/stage-timing-20260918/`。

| 文件 | 字节数 | 公开文件 SHA256 | 与历史摘要关系 |
| --- | --- | --- | --- |
| before.log | 1047 | `42b96e686b28ee3905d059f7e8ab20222a3fc311cab07929adcea28d44025e95` | LF 转 CRLF 后匹配原摘要 |
| after.log | 558 | `d79ac09be886e23fe06973acf80c98cb654d6ab891808becbe9107c63674bdf1` | LF 转 CRLF 后匹配原摘要 |
| mutant.log | 735 | `e248163498bf3592a84e5ebf203a9f69ce5d986ac34db70a29a4f6fc8baa75b5` | 公开字节直接匹配 |
| race.log | 65 | `adbf8fe197fe05cf08bf180ba939b4955c6533e84c1ad6432001ab0d75f926dc` | LF 转 CRLF 后匹配原摘要 |
| receipt-package.log | 67 | `ce85601219aff663690b0f9ad62b95744313227e1e27b510ccb3e672da2d46ef` | LF 转 CRLF 后匹配原摘要 |

本次 git diff --check 和带仓库配置的 gitleaks Git范围扫描通过。此记录不把历史失败变成通过，不提升平台总体状态。合并前仍须新head远端必要检查通过。

## 其余分支本次判断

#68 按用户明确要求排除。#56 的 Windows 符号链接负向前置缺口未关闭，#57 仍与main冲突。#80→#81→#82→#83为Windows在研栈，#84/#85/#86基于#83继续开发；#83–#86远端 agentshield/runtime-security-toolchain 失败，且正式签名与最终集成回归仍有缺口，不整体合并。#44/#78虽为证据草稿，本批不替其完成独立内容/隐私复核，也不标作已经验收。后续以最新提交重新判断，不能按本表永久冻结进度。
