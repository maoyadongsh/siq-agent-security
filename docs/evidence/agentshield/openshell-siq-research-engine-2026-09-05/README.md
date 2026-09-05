# OpenShell 接入（research-engine 隔离网关，2026-09-05）

未改 `siq-research-engine` 代码。AgentShield 未执行 `openshell gateway start`。

## 事实

- 分析助手运行面选择：`var/openshell/runtime-selection/siq-analysis.json` 为 `profile=siq_analysis`、`target=openshell`（对方仓库已有配置）。
- 接入时 `siq-openshell-dev`（`https://127.0.0.1:17671`）进程已死，残留 2026-08-19 PID。用对方现有 `gateway_start_recovery._remove_stopped_runtime_evidence` 清残留后，由人类侧运行 `scripts/openshell/start_gateway.sh`（未改脚本）。
- AgentShield：`SIQ_AS_OPENSHELL_ENV_SH=/home/maoyd/siq-research-engine/scripts/openshell/env.sh` → `openshell doctor` / `probe`：`probe_ok=true`、`identity_ok=true`、`tier=L3`、`source=env_sh`、`started_gateway=false`、握手网关名 `siq-openshell-dev`、CLI `v0.0.83`。
- 只读 `sandbox list`：仅 `siq-as-live`（2026-08-13，AgentShield 演示沙箱残留，Phase Ready）。未见正在跑的公司级 `siq_analysis` 沙箱。未对该沙箱 `policy set`。
- 宿主上 `siq_assistant` Hermes（`:18642` 等）是 Host 进程，不是 OpenShell sandbox。

## 结论

L3 **握手**已对 research-engine 隔离网关成立。分析助手「完整跑在 OpenShell 上」是对方产品链路与路由配置；本机此刻没有活动的分析沙箱可做网络段读回闭环。矩阵仍不改 `supported`。
