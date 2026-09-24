# E139：已登记 OpenShell 多网关选择与真实策略读回

日期：2026-09-23。接续 UX-03 环境发现任务，外部检查 SEC-F01–SEC-F10 继续保留在后续清单。总目标保持 active，未替换已安装发行版。

## 用户可完成的操作

页面读取本机 OpenShell 已登记网关，用户从下拉框选择后，直接查看对应沙箱并读取所选沙箱策略。CLI 已可从 PATH 找到时，不需要手填网关名称、地址或编辑环境变量才能完成此查看流程。选择 ID 保存在浏览器会话中，刷新及进入运行环境页后会用新登记清单恢复选择。

登记消失、清单读取失败、网关不可达与网关没有沙箱分别表达；不静默回退到默认网关。切换选择清空旧沙箱和旧策略，取消旧页面读取，迟到结果不能覆盖新选择。该入口只改变查看范围，智能体实际运行位置仍由原运行配置决定。

原有默认环境发现与“读取当前策略”入口保留。用户可以返回默认配置；页面操作不调用原生 `gateway select`，不修改当前服务的执行客户端，不创建或执行沙箱，不写策略或创建权限。

## 实现与边界

- `GET /v1/openshell/gateways` 使用既有明确 CLI（显式 CLI/endpoint 或 PATH）执行 `gateway list --output json`。最多 128 个登记、1 MiB 清单；拒绝重复 JSON 键、重复名称、缺失字段、非法地址和多个 active 标记。仅投影名称、地址、是否原生默认及不透明 ID/指纹，不返回原生 auth/source 等私有元数据。
- `POST /v1/openshell/gateways/targets` 仅接收已发现 ID 和配置指纹；`POST /v1/openshell/gateways/inspect` 再接收原沙箱 UUID、名称和端点指纹。管理凭据才可调用，不能通过请求指定任意 URL 或命令。
- 服务端在读取前后重读登记和 CLI 身份。选定网关使用独立只读 Client，显式绑定原登记名及地址；认证由原生 CLI 使用既有认证材料，产品接口不复制或返回私钥。不继承绕过 TLS 的开关。
- 沙箱清单与策略读回核对真实网关名称；策略读取沿用 UUID、端点、修订和摘要复验。完整性冲突返回失败，不能将 CLI 未取得清单解释为沙箱数量为零。
- 五个独立 v1 合同嵌套原 targets/inspection v1；保留原 HTTP 接口。浏览器在首页和运行环境页复用同一选择和读取组件。

`env_sh` 来源不能固定实际 CLI 时，不提供多网关选择，仍保留原环境读取。CLI 必须支持登记清单 JSON；没有因此自动升级 CLI。任意项目私有 XDG/CLI/profile 的自动寻找与登记仍未完成。

本次真实验证显式沿用研究项目已有 XDG 配置目录，PATH 场景将同一已核验 CLI 的只读代理加入隔离测试进程 PATH，并移除显式 CLI/endpoint/name/env-script 配置。因此证明的是“从 PATH 发现 CLI 后，复用该 CLI 当前配置上下文的多个登记”，不能表述为已经自动发现所有项目的私有配置目录。

## 实测结果

最终候选：`var/flagship/ux-e139/siq-agent-security-v2`。

SHA-256：`2b82b9e7b7ca1bf5e09afbd3f3edc5155bdebdf7457c57675805502572de63f7`。

原生 CLI 为已有固定 OpenShell 0.0.83，SHA-256：
`04158e0e24a621a60bcc6b390672853d58cbc5ed7412ac5e0a15d4cffeee17b7`。

| 验证 | 结果 | 实际覆盖 |
| --- | --- | --- |
| 显式 CLI 配置下多网关浏览器 | **18 项通过** | 真实登记→选择→真实沙箱→真实策略；切换时取消旧读取，刷新恢复；跨网关拒绝、登记漂移/消失、CLI 故障恢复；手机尺寸实际操作 |
| PATH 发现下多网关浏览器 | **19 项通过** | 移除显式 CLI/网关地址设置，原默认入口尚不可固定策略读取；选择已登记网关后同一完整旅程通过 |
| 原默认入口浏览器回归 | **15 项通过** | 原沙箱选择与策略读取、库存扫描不取消读取、过期状态、错误恢复、页面刷新及手机尺寸；同一最终候选 |
| 前端 | **41 文件、257 项通过** | 包括共享 Go 样例及非法/歧义网关响应；类型检查和本地 UI 构建通过 |
| Go | **全模块测试通过，44 个有测试包** | `go vet ./...`、产品 Go 源码格式检查通过；新解析/选择/管理边界及既有策略读取聚焦竞态检查两包通过 |
| Python 合同 | **1 项通过，覆盖 5 个新合同与 Go 样例** | 必填字段、禁止私钥字段、不可用不冒充空清单、禁止将策略读回标为强制效果；1 个既有 Starlette/httpx 弃用 warning |
| Ruff | **`ruff check app` 通过** | 本批没有 Python 业务实现变化 |
| 交叉构建 | **Linux amd64/arm64、macOS arm64、Windows amd64 通过** | 最终嵌入 UI；不等于 macOS/Windows 原生多网关验收 |

三组浏览器检查有重叠，不把数量相加当作独立功能完成数。原生网关为 `siq-openshell-dev` 和 `siq-openshell-scope-validation`；前者有真实就绪沙箱，后者的真实空清单被明确识别。故障通过隔离 CLI 代理模拟输出变化/失败，未篡改用户登记或证书。代理只允许只读命令；结束前后比较全部登记 metadata 摘要、native active 标记和默认沙箱清单，均保持一致。

Vite 构建通过，但主入口超过默认 500 kB 提示阈值，有 chunk-size warning；本批未通过提高阈值掩盖提示，也不据此宣称已完成加载性能验收。首次使用耗时、新手完成率及最终安装包体验仍按原任务书验收。

## 工程检查中补齐的约束

首轮真实浏览器 v1 已通过 18 项。收口时补充了“策略读取前后真实网关名必须匹配选定登记”的显式参数校验，并补负向测试；同时将选定登记的来源文案明确为“已登记网关”。最终 v2 重新通过上述三组真实浏览器检查，v1 记录独立保留，不借用其身份替代 v2。

## 证据与复验

- [E139 脱敏 JSON](../evidence/flagship-optimization-20260921/ux-openshell-gateways-e139.json)
- 证明器：`scripts/personal-experience/openshell-gateways-browser-smoke.py`。
- 原入口回归：`scripts/personal-experience/openshell-discovery-browser-smoke.py`。
- 日志、截图及四目标构建：`var/flagship/ux-e139/`。

```bash
python3 scripts/personal-experience/openshell-gateways-browser-smoke.py \
  --path-discovery \
  --binary var/flagship/ux-e139/siq-agent-security-v2 \
  --hermes-cli /home/maoyd/siq/hermes-agent/.venv/bin/hermes \
  --openshell-cli /home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell \
  --xdg-config /home/maoyd/siq-research-engine/var/openshell/xdg/config \
  --gateway siq-openshell-dev --endpoint https://127.0.0.1:17671 \
  --out-dir var/flagship/ux-e139/browser-path-recheck
```

`--gateway/--endpoint` 在 PATH 模式中只用于识别预期基线；证明器不把它们配置给候选服务。去掉 `--path-discovery` 验证显式 CLI/endpoint 模式。测试结束停止并清理自建候选，原服务/登记/策略无写入，因此不需要撤回用户配置。

## 接续

UX-03 仍需项目私有配置接续、原生凭据继承等；继续 UX-04/05 权限简化和 UX-11 业务结果产物、企业向导与发行验收。多网关查看不能证明智能体实际进入所选沙箱或隔离有效。本批没有提交、推送或更新已安装发行包，没有修改 Hermes 0.21 基线。
