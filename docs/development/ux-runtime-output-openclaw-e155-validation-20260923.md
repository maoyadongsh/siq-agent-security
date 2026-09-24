# OpenClaw 原生输出与双框架阅读体验（E155）

日期：2026-09-23。承接 E154 / UX-11，总目标保持 active。

## 结果与修复

真实 OpenClaw 2026.9.5 插件加载器、before-tool 包装器、原生文件工具和 after-tool relay 已接通受管理身份的输出采集与运行详情。两个宿主会话使用同一 sessionKey、不同 sessionId，验证重置后的新会话不会复用旧任务采集授权，也不能看到旧会话输出。越权写被实际拒绝且目标文件不存在，拒绝不被计作成功输出。重启守护进程后保留的密文仍可按历史来源核验并明确确认读取。

现场页面重复展示 OpenClaw 两份相同正文，并暴露多条 JSON 字段路径。本批增加只读显示投影：对 read 工具已知的 5 个文本字段，核对两份正文完全相同后只显示一份，原采集字段仍可展开核对。非文本、重复路径、正文不一致、超长或存在额外错误/截断字段时完整保留原字段显示。每个字段只解析一层且最多 64 Ki 字符；不执行 HTML，不改变原文、摘要、权限、采集开关、任务状态或接口合同。

Hermes 保留上一批的正文展示。共用原生验收脚本增加 `--platform openclaw`、隔离 OpenClaw 配置与真实宿主模块摘要；异常及人工中断都不能留下成功报告。没有修改宿主源码、适配器代码或用户模型配置。

## 本批验证

| 验证范围 | 实际结果 |
| --- | --- |
| OpenClaw 原生 → 页面 | **12 项通过**：安装/配置保留、默认不保存、授权不补录、真实钩子采集、新会话隔离、越权写不执行、服务重启、目录不读取正文、明确确认、文本展示/原字段展开、375px 布局、关闭/刷新清除 |
| Hermes 同候选原生回归 | **12 项通过**，同一输出页面及既有正文格式正常 |
| 输出页失败/恢复回归 | **11 项通过**，包含迟到响应不恢复正文、失败后显式重试、快照变化、删除后拒读、凭据字段排除 |
| Web | **53 文件 / 290 项通过**；本地/企业构建成功；新增 3 项 OpenClaw 格式投影测试包含未知/额外/冲突字段负向样例 |
| Go 定向与候选 | 输出路由定向测试通过（ui 过滤无测试）；Linux arm64/amd64、Darwin arm64、Windows amd64 构建通过，当前 Linux 原生候选可执行 |
| 工具检查 | 新脚本 Ruff、Python 编译、`git diff --check` 通过 |

最终原生记录：`var/flagship/ux-e155/openclaw-complete/result.json`、`hermes-complete/result.json`；输出回归：`output-regression/result.json`。已检查 OpenClaw 最终桌面与 375px 截图，正文无重复、字段可折叠、关闭操作可见。Go/API 全量未在本批重跑，上一批历史结果不重新计为本批验证。现有前端包体积提示保留。

首次夹具错误地沿用 Hermes 的 read_file 授权名，OpenClaw read 因不在允许列表而被拒；修正为各平台实际工具名后重跑通过。`openclaw-first` 保留失败结果，`openclaw-v2` 是改正文前的证据，不替代最终候选。为正确记录人工中断，最终脚本小修后再次运行两框架，`*-complete` 为最终脚本身份。

## 复验与交付边界

```bash
python3 scripts/personal-experience/native-runtime-output-browser-smoke.py \
  --platform openclaw \
  --binary var/flagship/ux-e155/siq-agent-security \
  --openclaw-root /home/maoyd/.nvm/versions/node/v24.21.0/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v24.21.0/bin/node \
  --out-dir var/flagship/ux-e155/recheck-openclaw

python3 scripts/personal-experience/native-runtime-output-browser-smoke.py \
  --binary var/flagship/ux-e155/siq-agent-security \
  --hermes-root /home/maoyd/siq/hermes-agent \
  --out-dir var/flagship/ux-e155/recheck-hermes
```

输出目录须不存在。[证据清单](../evidence/flagship-optimization-20260921/ux-runtime-output-openclaw-e155.json) 固定新候选、源码、原生宿主模块、浏览器记录、截图和测试摘要。候选在 `var/flagship/ux-e155/`，未替换已安装程序。回退 E154 只失去 OpenClaw 正文显示优化，存储/接口兼容；无需迁移，无新依赖。

测试只访问自有临时状态及合成文件；结束停止进程、清理临时根。没有模型调用、用户业务数据读取或真实配置/网关/沙箱更改。OpenClaw after relay 由夹具调用，属于真实组件组合验证，不是完整模型驱动会话或 OpenShell 沙箱内业务验证。未提交、推送、发布，交叉编译不代替其他 OS 的原生安装验收。

本批关闭 UX-11 两框架原生工具输出到详情页的对应子项。正式业务报告及文件权限、名称与生命周期、人工结案/安全重提、安装与生产验收继续，SEC-F01–F10 保持后续顺序。
