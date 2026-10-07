# OPT-08 D2i：OpenShell、Hermes 原生工具与在线 Authority 同次联验

日期：2026-10-07。状态：同次真实运行联验通过；OPT-08 保持 implementing，主任务完成 9/16（56.25%）。

## 本批结果

本批首次将独立 OpenShell 沙箱中的实际 Hermes 原生工具、双向内核凭据通道、宿主发布/反向运行核验、真实 Go HTTP 裁决、签名安装来源和实际文件效果串接在同一次运行中。没有使用合成 allow/deny 回调替代 Go Authority。

两个 Skill 的内容是合成测试材料，但导入、权限构建、批准、安装、激活、原生身份与会话均调用实际 Store 实现，具有真实签名和安装记录。受控测试操作员生成授权；这不是第三方人员审批、正式发布身份或真实业务数据验收。Go 服务使用 opt-in `_test.go` 启动真实 `server.New/Handler/receipt.Engine`，不是日常 `serve` 的发行部署。

| 同次调用 | 结果 | 签名来源与独立效果 |
| --- | --- | --- |
| 加载 reader | allow | 实际 `skill_view` 读取前完成安装/来源校验；初次加载调用尚无 Skill 上下文 |
| reader 读取输入文件 | allow | 1 层 Skill 上下文；实际 Hermes `read_file` 返回预期合成输入 |
| reader 写入文件 | deny | 1 层上下文；`grant_scope_violation`，宿主确认目标不存在 |
| 同任务切换到 writer | allow | 加载受保护第二个 Skill，保留 reader 祖先 |
| 切换后尝试写入 | deny | 2 层上下文；reader 祖先继续限制写入，宿主确认目标不存在 |
| 独立任务加载 writer | allow | 新任务独立登记，未借用前一任务的上下文 |
| writer 在批准目录写入 | allow | 1 层上下文；真实 Hermes `write_file` 产生文件，宿主独立核对摘要 |
| writer 写入批准目录外 | deny | `grant_scope_violation`；宿主确认目标不存在 |

8 项运行检查全部通过，8 条实际回执形成可验证签名链：5 次 allow、3 次 deny。切换后的拒绝具有两层上下文，证明它不是“新 Skill 覆盖原权限”；独立 writer 的合法写入成功，证明它不是全部拒绝造成的假阳性。

此处的文件效果由宿主从已固定进程根目录独立读取，不仅依赖模型回答或工具返回的成功标记。所有模型调用为零；当前仍是确定性调用真实 Hermes 工具，没有运行模型对话或智能分析助手日常业务入口。

## 实现与联验修复

1. 增加 [native-decision-relay/v1](../../packages/contracts/native-decision-relay.v1.md)：通过已有双向认证通道转交固定 `/v1/decide`，运行身份凭据只在宿主侧持有。模型不能指定端点、头、凭据或额外 Authority；固定请求主体、64 KiB 限额、5 秒预算、无重定向或重试。运行核验在请求前后执行，只返回实际裁决的 action 和 receipt_id。
2. 修复运行核验租约的 UTC 到期时间漂移：登记时固定到期时间，每次回查仍重新验证 guard 和单调时钟。此前反复以 UTC-now 加剩余时长生成截止时间，微秒级漂移会误使签名调用超过当前期限。没有延长租约或放宽失效检查。
3. 增加仅对有效原生调用适用的受保护 Skill 加载分类：严格 `{name, file_path?}` 的 `skill_view` 作为 `skill.load/tool.invoke` 工作流处理。普通同名工具、未验证调用、路径穿越和额外参数保持拒绝；Intent 的身份、期限、工具、效果、参数和资源约束完整保留。正文返回前的实际安装来源校验继续必需，不能因工具分类获得任意文件读取权限。
4. 固定独有派生镜像覆盖层的目录/文件权限。Docker COPY 会保留宿主组写位；运行核验实际发现 tools/agent 目录和许可证文件不满足保护要求，构建阶段修正权限后才通过。原业务镜像和日常网关保持不变。

合成 Skill 初次加载因 unknown 效果失败时，后续调用只是 Agent 基线行为，不能用来证明 Skill 权限交集。本批保留这些失败结果，最终只有加载成功、来源核对有效、完整上下文匹配的第 07 次运行计入通过。

## 验证范围

- Python 受影响的在线映射/转发测试：30 项通过，包括 allow/deny/hold、主体替换、凭据隔离、非法/超大响应、运行失效和租约稳定性。
- Go 受影响的 receipt、intent、runtimeaction、skillcontext、server 五包完整测试通过。独有 OpenShell 联验另以显式 opt-in 运行，正常单测不启动 Docker 或本机网关。
- receipt、intent、server 的新增/在线定向 race 通过；包含 11 组原生加载形状/来源用例与 9 组 Intent 约束用例。
- 相关五包 vet、修改 Python 的 Ruff、`git diff --check` 通过；Linux amd64/arm64、macOS arm64、Windows amd64 编译通过，编译不代表后两者原生验收。

最终执行命令：

```bash
python patches/hermes/run_openshell_runtime_probe.py --online --output var/optimization-20261007/opt08-openshell-online-07
var/mako117-20261006/worktree/apps/control-api/.venv/bin/python -m pytest adapters/runtime/hermes-agentshield/tests/test_native_online.py adapters/runtime/hermes-agentshield/tests/test_native_relay.py -q
cd apps/agentshield
go test ./internal/receipt ./internal/intent ./internal/runtimeaction ./internal/skillcontext ./internal/server
go test -race ./internal/receipt ./internal/intent ./internal/server -run 'TestProtectedNativeSkillLoader|TestNativeSkillLoader|TestNativeOnline' -count=1
```

同次原始结果位于本机 `var/optimization-20261007/opt08-openshell-online-07/`；前 01–06 次失败/诊断尝试分别保留，不计为通过。临时沙箱删除成功，独有网络确认空后移除，原网关配置、元数据和 TLS 摘要保持不变。运行凭据仅存在私有临时状态，由其创建者结束后清理；不提交凭据、原始服务日志、镜像或完整状态。

可提交的检查摘要、回执投影与源码摘要见 [结构化证据](evidence/optimization-20261007/native-openshell-online.json)。没有重跑未修改的前端或 Python 控制面全量。

## 下一步与完成边界

仍须将受保护启动和原生身份登记接入智能分析助手日常入口，完成真实业务 Skill、并发、撤权、内容漂移、过期、结束后调用和人工审批重试等验收，并完成同候选四臂对照与剩余优化任务。当前管理 HTTP 新身份创建仍关闭，镜像覆盖清单仍不标记生产启用。不能将这 8 项同次联验等同于 OPT-08 全部完成或 OPT-00–15 整体完成。
