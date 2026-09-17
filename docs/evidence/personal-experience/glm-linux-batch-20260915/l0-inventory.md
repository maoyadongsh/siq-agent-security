# L0 基线盘点（R06/R04/R07 批，2026-09-15 15:39 Asia/Shanghai）

## Git 与源码

- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- 分支：`kimi/personal-v4-r01-20260914`；HEAD = `efad8407c84b7b8f626cb06421287e7632c83a46`（与已验收基线一致）
- `git merge-base --is-ancestor efad840… HEAD` → 通过；`git diff --check` → 干净
- 未提交路径：仅本交接文档 `docs/glm-linux-r06-r04-r07-execution-prompt-20260915-153142.md`（保留，不清理）
- 无其他窗口并行修改迹象（工作树除上述文件外干净）

## 环境

- OS：Linux 6.17.0-1014-nvidia，aarch64，20 CPU，内存 121Gi
- Go 1.26.5；Node v22.22.2；Python 3.13.12；uv 可用（脚本测试用 `uv run --with pytest`）
- systemd 用户 manager：`degraded`（可用；degraded 为既有生产单元状态，本批不修复不重启）
- `XDG_RUNTIME_DIR=/run/user/1000`；用户 Linger=yes（既有状态，本批不改）
- 图形会话：本会话无 GUI 观察能力，通知视觉确认层继续保留缺口

## OpenClaw 宿主（真实）

- 可执行：`~/.local/bin/openclaw`（bash wrapper → `~/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw/openclaw.mjs`），版本 `OpenClaw 2026.5.12 (f066dd2)`
- 安装根：nvm 全局 node_modules；配置根 `~/.openclaw`、`~/.config/openclaw`
- **日常配置 `~/.openclaw/agentshield.json`**：endpoint `http://127.0.0.1:47611`、block 模式、token 指向主仓 `~/siq/siq-agent-security/.../.state/token` —— 生产态，不得触碰
- 真实 skills（lark-* 等生产素材）位于 `~/.openclaw/skills` —— 测试只使用本批专属隔离 profile

## 现有服务/端口（本批不得触碰清单）

- systemd 用户生产单元：`hermes-gateway-siq@*.service`、`hermes-gateway-siq-ic@*.service`（10+ 实例，active running）、`siq-funasr-vllm.service`、`siq-research-engine.service`
- 监听端口 `127.0.0.1:8080`（非本批进程，归属未查明 —— 只读记录，不停止、不占用）
- 用户日常 OpenClaw 状态目录与 agentshield.json（见上）
- 当前无 agentshield 自身注册的用户单元

## 环境操作约束落点

- systemd 真实用户总线属当前登录用户；测试单元必须实例专属命名 + FragmentPath/ExecStart/状态目录归属复验，结束后复验原单元不存在
- 不 pkill/killall；只停止本批创建且身份确认的 PID/单元；不启用/停用 linger；不重启整机
- 隔离 HOME/OPENCLAW profile 只传给测试子进程，不改当前 shell 环境

## 候选构建

- 平台候选：`/tmp/siq-batch-20260915/bin/agentshield`（go build -trimpath，源 HEAD efad840）
- sha256 `15d688fdd4652e9efb544ece769142b60725bc0a5d2deae233062f6b910e0701`
- 每次源码/embed 改动后重建并记录新摘要；真实宿主测试一律引用此绝对路径

## 工作包依赖表

| 包 | 可执行（本机） | 需先修复/确认 | 外部条件受阻 | 解除条件 |
| --- | --- | --- | --- | --- |
| L1 R06 Linux 生命周期 | client-install/setup/service-*/teardown 全链路 + 真实 systemd 用户单元测试 | 正式签名密钥不可用 → 用既有测试签名缝，标为测试层 | 登录自启动/整机重启的实机验证（无法自动注销/重启） | 人工登录/重启验收 |
| L2 R04 OpenClaw 更新 | 真实 OpenClaw 2026.5.12 进程 + 本地目录来源 + 隔离 profile | 需确认原生 Skill 重载/会话重建语义 | 公网 Git 来源（R03 生产关闭） | 真网 + R03 解除 |
| L3 R07 完整旅程 | 真实浏览器（headless Chromium/Playwright）+ 真实 daemon + 真实宿主 | 通知视觉确认层（仅总线回执可证） | OS 通知弹窗视觉、真人体验验收 | 人工视觉验收 |

## 测试隔离与回收责任

- 状态目录：`/tmp/siq-batch-20260915/state/<场景>`（0700，`SIQ_AGENT_SECURITY_STATE_DIR` 注入子进程）
- OpenClaw 隔离 profile：按既有 smoke 脚本模式（OPENCLAW 专属 env + 专属目录），全部由本批脚本创建/回收
- systemd 单元：`siq-agentshield-batch-*.service` 前缀命名，runtime-only，测后 `--confirm-unregister` 并复验缺席
- 端口：随机可用 loopback 端口，由测试分配，结束后复验无监听
- 证据目录：`docs/evidence/personal-experience/r06-linux-lifecycle-<ts>/`、`r04-openclaw-native-update-<ts>/`、`r07-linux-user-journey-<ts>/`、本目录（L0/批次级）
