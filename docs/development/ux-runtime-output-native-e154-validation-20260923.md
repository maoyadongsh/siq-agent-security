# Hermes 原生输出到页面与正文可读性（E154）

日期：2026-09-23。承接 E152/E153 与 UX-11，总目标保持 active。

## 本批结果

已用本机 Hermes 0.21.0 的真实插件加载器和工具分派器，跑通安装后的钩子 → 原生读文件 → 授权加密采集 → 服务重启 → 精确运行目录 → 页面确认查看。测试不直接 POST 采集接口，也未替换钩子或伪造成功响应。Hermes 源码基线为 `42f0c8179e30cf6ba4cba0a8f2852e609f717773`，实际 CLI、分派器、插件加载器和适配器摘要见证据。

现场发现文件输出被两层 JSON 编码，原页面出现大量转义字符。现已修复显示：对已知 Hermes 文本文件返回格式，前置“读取文件的输出”，保留工具附带行号；原始采集字段可展开核对。截断时明确提示。遇到未知工具/平台、额外错误或警告字段、二进制/图片、格式异常、超长输入时保留原字段，不猜测正文，不隐藏未识别信息。

仅新增显示投影，最多解析两层、64 Ki 字符；原文和摘要未改写。正文保持 React 纯文本输出，脚本片段不会执行。没有新增接口、权限、存储格式、采集范围或自动读取行为；查看输出不表示任务成功或报告发布。

## 实测与验证

| 检查 | 本批实际结果 |
| --- | --- |
| 原生 Hermes + 浏览器 | **12 项通过**：管理 API 真实预览/安装、保留另一配置；默认不保存；授权不补录；原生 post hook 只产生一条输出；另一会话不可借用授权/输出；越权写未执行且不产生成功输出；守护进程重启后来源仍可验证；列表不读正文；明确确认读取；正文优先/原字段展开无额外请求；375px 操作；关闭/刷新清除 |
| 原输出页面回归 | **11 项通过**：默认关闭/空列表、纯文本/凭据字段排除、关闭与焦点、刷新不重读、迟到响应、失败后显式重试、快照变化和删除后拒读 |
| Web | **53 文件 / 287 项通过**；本地与企业构建成功。新增 3 项格式投影测试覆盖两层编码、不改原文和未知/异常格式退回 |
| Go 定向 | `go test ./internal/ui ./internal/server -run 'ActivityOutputs\|RuntimeOutput'` 通过；ui 包无测试，server 输出路由测试执行通过。未改 Go 逻辑，本批未重跑 Go/API 全量，不能重复计作本批结果 |
| 脚本 | 新脚本 Ruff 与 Python 编译通过；`git diff --check` 通过 |

原生脚本：`scripts/personal-experience/native-runtime-output-browser-smoke.py`。最终记录：`var/flagship/ux-e154/browser-readable/result.json`；旧输出回归记录：`var/flagship/ux-e154/output-regression/result.json`。已查看最终手机截图和此前桌面布局；内容换行，关闭按钮可见，字段折叠保留。

本批早期使用 E153 二进制完成 11 项原生链路检查，随后针对可读性修改重新构建、重跑为 12 项。`browser-first`/`browser-final` 为修改前证据，不代替 `browser-readable`。首次类型检查发现活动平台应取可信绑定字段，已修复并重新通过构建；失败日志保留，不计为通过。

## 候选、复验与边界

[证据清单](../evidence/flagship-optimization-20260921/ux-runtime-output-native-e154.json) 固定源码、测试结果、截图和新候选摘要。候选在 `var/flagship/ux-e154/`，未替换已安装版本。Linux arm64/amd64、Darwin arm64、Windows amd64 分别交叉构建；非 Linux 平台不据此宣称原生验收完成。

```bash
python3 scripts/personal-experience/native-runtime-output-browser-smoke.py \
  --binary var/flagship/ux-e154/siq-agent-security \
  --hermes-root /home/maoyd/siq/hermes-agent \
  --out-dir var/flagship/ux-e154/recheck-native

python3 scripts/personal-experience/runtime-output-browser-smoke.py \
  --binary var/flagship/ux-e154/siq-agent-security \
  --out-dir var/flagship/ux-e154/recheck-output
```

输出目录需不存在。脚本只在自有临时配置/状态/文件中运行，结束停止守护进程并清理临时根。没有修改真实 Hermes/OpenClaw 配置、业务文件、网关、沙箱或模型服务。无新依赖/迁移；未提交、推送、发布。回退到 E153 仅失去本批正文显示优化，密文格式和读取权限兼容。

这是真实原生工具分派链路，工具请求和文件为合成测试数据；没有调用模型，不是自然语言业务任务、完整 Hermes CLI 会话、OpenShell 内执行或正式报告发布验收。本批关闭 UX-11 的 Hermes 钩子到输出页子项；OpenClaw 对应链路、业务报告/文件权限、业务名称与生命周期、人工结案/安全重提、安装发行继续推进。SEC-F01–F10 仍按用户要求后续处理。
