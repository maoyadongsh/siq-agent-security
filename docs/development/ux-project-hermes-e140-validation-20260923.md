# E140：已登记项目的 Hermes 角色、Skill、模型与原生接入

日期：2026-09-23。UX-03 接续；总目标 active，外部安全检查 SEC-F01–SEC-F10 仍为后续任务。

## 用户可完成的流程

用户在“高级选项：补充目录与扫描范围”登记一次项目，预览后开始扫描。项目的
`.hermes`、`agents/hermes` 和一级 `profiles/*` 中已有 Hermes 角色进入实例列表，
对应 Skill 和模型配置同步发现。用户不需要逐个输入 profile、修改 HERMES_HOME，
或为模型检查再登记一次路径。

接入按钮复用原有预览、确认应用和原生插件启用；安装后可直接运行 Hermes 自检，
验证正常读取、越权写入拦截、拒绝后恢复读取，以及回执签名，再进入同一次运行记录。
同名默认角色和项目角色保留不同实例 ID，可展开位置核对；项目登记在刷新和服务重启后保留。

这不是所有任意项目布局的自动发现：用户首次仍需提供一个项目根目录。没有读取
项目启动脚本、执行扫描到的内容或自动安装插件；权限仍需原流程明确操作。

## 本批实现

1. `hermeshome` 增加已登记项目范围，库存、模型、管理实例、安装预览、运行身份、
   Skill 目标、命令行实例和库存复用同一路径身份。旧实例 ID、default/active 不变。
2. 仅扫描两个约定位置及一级 profiles；普通容器不当角色，需普通文件 `config.yaml`
   或 `SOUL.md`。不跟随目录符号链接。最多 16 个项目、每容器 64 个 profile、
   项目新增实例总计 128；不可读、失踪或超限分别产生 issue。
3. 新增独立 `local-adapter-instances/v3` 合同：
   `GET /v1/adapter/instances?platform=hermes&include_projects=true`。
   source 可为 `registered_project`。旧请求仍返回原 v1 范围，WorkBuddy v2 不变。
4. 项目移走、标记消失或目录换成符号链接后不能解析旧实例，过期安装计划拒绝。
   登记读取失败不能继续接受未知项目 ID。发现不创建权限。
5. 完成扫描后同步刷新模型清单；进行中的模型检查先完成，再更新清单。
   自动刷新按 ID/指纹保留仍有效的检查结果；配置漂移或读取失败清除旧结果。
   用户主动“重新发现模型”仍清除旧连接检查展示。
6. 命令行 `inventory`、`export`、`sync` 共用的库存入口也读取已登记范围，
   避免页面发现的项目在命令行报告里消失。

## 最终候选与验证

候选：`var/flagship/ux-e140/siq-agent-security-v3`
SHA-256：`8cde5c5990955e1bd51748ec044a247518bf7be0a8d3a60569f15c2e5997c852`。

| 验证 | 结果及范围 |
| --- | --- |
| 项目真实浏览器与原生 Hermes | **26 项通过**：预览不保存、单次登记、模型自动更新、既有私密 env 引用、扫描不打断检查、相同指纹保留结果/变化失效、角色与 Skill、取消不写入、安装读回、原生自检五条回执、运行详情、移动端操作无遮挡、失踪拒绝/恢复、服务重启及 CLI 一致 |
| 模型列表原入口回归 | **13 项通过**：Hermes/OpenClaw、认证/限流/服务错误、配置漂移和恢复、手机入口；与上行同一最终候选 |
| Web | **41 文件、257 项通过**；类型检查及嵌入前端构建通过 |
| Go | **全模块 44 个有测试包通过**，vet 与产品源码 gofmt 通过；解析/管理两包聚焦 race 通过；CLI 登记范围正负向通过 |
| Python | **1 项新合同测试通过**，验证真实 Go v3 样例、版本/权威状态负向；本批不冒充 Python 全量重跑 |
| Ruff | `ruff check app` 通过 |
| 四目标构建 | Linux amd64/arm64、macOS arm64、Windows amd64；原生功能验收范围仍为 DGX Spark/Linux |

Vite 主入口仍有超过默认 500 kB 的提示；Python 合同测试有既有 Starlette/httpx
弃用 warning。没有调整阈值掩盖提示，不把构建通过当成加载性能验收。

本批在隔离候选内实际登记了 `/home/maoyd/siq-research-engine`，真实
`agents/hermes/profiles/siq_analysis` 出现在项目实例列表，前后 `config.yaml` 摘要一致。
研究项目只参与发现，不对真实角色安装或自检。插件接入、模型列表检查、原生工具
allow/deny 和临时权限清理全部发生在自建合成项目；模型列表来自本地测试 HTTP
服务，没有云端推理或企业业务数据。原有 Hermes 0.21、OpenShell 和已安装发行包未改变。

## 保留的发现与修正

- 第一轮在真实项目断言处使用模糊名称，同时匹配 `siq_analysis` 和
  `siq_analysis_multi_market`，测试失败；改为精确匹配，后续通过。
- 第二候选回归复现自动刷新清掉刚返回的模型检查结果。前端改为按指纹保留结果，
  最终 v3 补验扫描中的检查、结果保留和配置变化失效，再跑两组浏览器。
- 移动端首张截图截在侧栏过渡动画中；最终证明器等待布局稳定，检查卡片边界和
  按钮中心可点击，再留截图。不能仅用元素内部无溢出来声称无遮挡。
- 收口时发现命令行库存未沿用登记范围，补齐实现及负向测试，最终候选重新验收。

历史失败和中间候选分别保留，不借用早期通过结果替代最终候选。

## 复验与回滚

[脱敏证据 JSON](../evidence/flagship-optimization-20260921/ux-project-hermes-e140.json)；
日志和截图位于 `var/flagship/ux-e140/`。

```bash
python3 scripts/personal-experience/project-hermes-browser-smoke.py \
  --binary var/flagship/ux-e140/siq-agent-security-v3 \
  --hermes-cli /home/maoyd/siq/hermes-agent/.venv/bin/hermes \
  --research-project /home/maoyd/siq-research-engine \
  --out-dir var/flagship/ux-e140/recheck
```

证明器只停止和删除自己创建的服务、项目与状态目录；研究项目只读。产品中的插件
卸载仍走原预览/确认接口；本批没有真实用户配置需要回滚，也没有提交、推送或替换发行版。

## 尚未完成的范围

UX-03 继续 active。任意布局的项目发现、项目私有 OpenShell 上下文的接续、完整
原生凭据继承、多 OpenClaw 配置根尚未完成；没有将登记目录等同于全部环境零配置。
后续继续权限操作简化、同名对象更清楚的上下文、业务结果产物、企业接入和安装版验收。
