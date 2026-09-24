# E141：工具勾选、只读方案与权限变更体验

日期：2026-09-23。对应 UX-05、UX-04/06 接续；总目标 active。

## 用户可完成的操作

权限编辑默认展示当前声明工具的中文勾选项，例如“读取文件（read_file）”“写入文件
（write_file）”“执行命令（terminal）”。用户可直接勾选，无需照着技术文档手写名称。
未知名称明确显示“自定义工具或工具组”；高级手动输入仍可展开。名称说明不冒充
原平台安装或运行事实。

“采用只读资料方案”只保留当前已选的明确文件读取工具，把已填读写目录转为只读，
清空本页网络和模型允许项。不会自行增加工具或目录；网络拒绝和后端保留权限/批准
条件保持。没有已选读取工具时禁用，避免给出无法执行读取的虚假方案。

方案只修改表单，显示“尚未保存”并可撤回。用户继续编辑后撤回入口消失，避免旧
快照覆盖新输入。保存仍是待批准状态；核对、批准、准备身份和确认接入沿用原链路。
本页说明其他权限和条件仍保留，不把“只读方案”或“清空允许范围”描述为撤销全部权限。

权限摘要也使用工具中文说明，并继续展示真实目录、端点、状态和到期时间。

## 实现与约束

- `permissionTools.ts` 仅解释当前工具名，原文用于提交，不做工具组扩展或名称重写。
  只读筛选只匹配 `read_file/read/cat/search_files`；通用 file 组、shell、网络工具、
  未知 MCP 名称不会因含 read 等文字被归入只读。
- POSIX 路径内部空格和逗号保留；Windows 路径原文保留，非法路径仍由后端拒绝。
  模板没有绕过现有资源校验、版本冲突检查、批准条件或身份绑定。
- 复用 `grant-resource-edit/v1`，没有新建后端授权通道或修改合同。
- 原生 HTML checkbox、fieldset 和文字标签支持键盘及移动端操作。现有组件、配色、
  弹窗与按钮体系保持，不增加前端依赖。
- 权限变更回归复现卸载预览忙碌：原前端把与卸载无关的身份变化纳入依赖，旧预览
  也未取消。现在按实际动作所需参数驱动预览，并用 AbortSignal 取消失效请求。
  只有服务明确拒绝 `adapter_busy` 的只读预览可每隔 1 秒重试，最多 2 次；其他
  错误、安装和卸载写入不自动重试，后端互斥继续保留。

## 最终候选与证据

候选：`var/flagship/ux-e141/siq-agent-security-v5`
SHA-256：`05033011fb52953a6dc29625dab169a843c728541d3df8e64b1fb2862aae7b3e`。

| 验证 | 结果及实际范围 |
| --- | --- |
| 权限编辑真实浏览器 | **20 项通过**：已知/未知工具、键盘切换、无读取工具禁用、模板不写后端、撤回、移动端、保存待批准、拒绝与逐次批准条件保留、版本冲突保留输入、读取失败禁止保存、清空及已批准不可编辑 |
| Hermes/OpenClaw 接入旅程 | **53 项通过**：两平台无需手填工具名，独立读回精确工具与目录，批准/身份/安装链，正常读取、移除写入拒绝且无文件效果、越界拒绝、停用阻断、运行记录与刷新 |
| 已有权限调整与卸载 | **17 项通过**：新草稿不改旧权限，旧身份明确撤销，新范围实际生效，旧会话不能复活，历史授权保留，原生插件注册恢复；注入两次预览忙碌后第三次真实预览通过，未自动重复写入 |
| 前端 | **42 文件、261 项通过**；本地嵌入 UI 和企业前端构建、类型检查通过 |
| Go | 最终候选对应全模块 **44 个有测试包通过**、vet、产品源码 gofmt 通过；四目标交叉构建通过 |
| 证明脚本 | 四个调整脚本 Python 语法检查通过；未改变 Python 业务实现或 Schema，本批未重跑 control-api 全量测试 |

三组浏览器场景存在重叠，不把 20/53/17 相加当独立功能覆盖率。

双平台旅程中的 Hermes 使用已安装适配器真实钩子和合成文件操作；OpenClaw 使用
实际原生插件及文件工具。权限替换中的 Hermes 原生命令用于启用/卸载插件，授权
判定探针经真实 HTTP，不冒充完整模型驱动会话。本批没有模型推理、云调用或用户业务数据。
macOS/Windows 只有交叉编译，不能外推为原生使用体验通过。

构建仍存在主入口超过 Vite 默认 500 kB 的提示，没有隐藏提示或宣称加载性能验收。
用户研究、实际安装包、完整企业向导与其他权限简化仍未完成。

## 失败记录和修正

1. 老资源证明器没有初始化新状态，候选按既有规则拒绝启动；补充真实 `init`，
   并隔离环境变量，未修改产品启动限制。
2. 老权限证明器仍使用旧标签且遗漏检查来源确认；对齐当前 UI，保留明确确认。
3. 工具输入折叠后，原测试用“输入框不可见”判断保存完成会提前读取。改为等待
   实际 resources 请求成功及编辑器关闭，再独立读回。
4. 修改权限后快速停用/卸载触发真实 `adapter_busy`，如
   `revision-v4/uninstall-failure.sanitized.json`。修复前端重复依赖与失效请求处理；
   最终候选额外注入两次 busy，验证有限恢复和原生卸载。

中间失败与早期候选保留在本批目录；最终通过记录均引用同一 v5 二进制，不混用身份。

## 复验与回滚

[脱敏证据 JSON](../evidence/flagship-optimization-20260921/ux-permission-tools-e141.json)；
日志和截图位于 `var/flagship/ux-e141/`。

```bash
python3 scripts/personal-experience/grant-resource-browser-smoke.py \
  --binary var/flagship/ux-e141/siq-agent-security-v5 \
  --out-dir var/flagship/ux-e141/resources-recheck
python3 scripts/personal-experience/environment-onboarding-browser-smoke.py \
  --binary var/flagship/ux-e141/siq-agent-security-v5 \
  --openclaw-root /home/maoyd/.nvm/versions/node/v24.21.0/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v24.21.0/bin/node \
  --out-dir var/flagship/ux-e141/journey-recheck
python3 scripts/personal-experience/permission-revision-browser-smoke.py \
  --binary var/flagship/ux-e141/siq-agent-security-v5 \
  --hermes-cli /home/maoyd/siq/hermes-agent/.venv/bin/hermes \
  --out-dir var/flagship/ux-e141/revision-recheck
```

模板保存前可撤回或取消；保存后按原待批准编辑/重新起草处理，已接入身份按原停用
流程撤销。验证只改自建临时 HOME/profile/state，结束清理自己的服务和文件。
没有更改用户模型、Hermes 0.21 基线、OpenShell 网关或已安装发行版；没有提交/推送。

## 下一步

UX-05 部分完成，继续优化权限审批与接入的步骤表达。UX-11 的业务结果产物与状态、
企业接入向导和安装版验收保持待办。外部安全检查 SEC-F01–SEC-F10 仍按用户排序在后续清单。
