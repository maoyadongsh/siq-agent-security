# LX03：OpenClaw 2026.9.4 隔离升级评估

日期：2026-09-19。结论：**暂不覆盖本机 OpenClaw 2026.5.12 安装**。新版可跑通本批基础功能链路，但原版宿主仍不能让 SIQ 批准型 hold 在执行前完成异步复查；升级本身不解除 LX03 的关键阻塞。

## 来源与运行边界

- [OpenClaw 官方 v2026.9.4 发行页](https://github.com/openclaw/openclaw/releases/tag/v2026.9.4)将该版列为 Latest；npm `openclaw@2026.9.4` 的包要求 Node `>=24.16.0 <25 || >=26.1.0`。本机默认 Node 22 不符合，新版隔离测试使用 Node 24.18.0。
- npm 包归档 SHA256：`4f1f656770461d4677dea755b1899cba12b912b06798c89a59e2f0c18688b761`。实际隔离安装使用 `--ignore-scripts --omit=optional`，不是对所有可选组件的安装验收。宿主入口 `openclaw.mjs` SHA256：`97464647c50a1420d530db948cb203826306ef6b3a84810b6801c338366cecaf`。
- SIQ 使用未签名第六代 Linux/arm64 候选 `67bc48c4f751f9f6334295b78346e1290bd6f9d1d4e02a8695ca1ef26eb43428`；隔离 HOME、合成模型/操作员和本地 daemon。原本机安装、共享用户配置和网关没有升级或重启。

## 一次定向功能实测

| 链路 | 结果 | 证据边界 |
| --- | --- | --- |
| 新版公共 CLI × 实际插件加载 × SIQ 托管安装 | **19/19 通过** | 原生会话自动登记、有效读取、越权写入执行前拒绝、原文按授权采集及撤销、身份撤销、签名回执验证；隔离安装与合成模型，不代表真实用户桌面验收。私有原始报告 SHA256 `de538775476b7469268d9facff399231e299d0ec3b8c953f07d07012e6e6835e`。 |
| 新版原版宿主 × SIQ 批准型 hold | **1/1 安全拒绝** | 平台审批请求未发起、执行零次、预留/观察零条、签名回执链通过。此负向通过不等于批准后效果跑通。私有原始报告 SHA256 `f462a0d95b3c595038a618bd7d8e7cc99046e4a4a143dfc317b423ab93f2a127`。 |

## 为什么升级仍不能关闭 hold

新版公开 hook 类型 `dist/hook-runner-global-DWDBlTB2.d.ts`（SHA256 `2b269c3ac632776a500ad3d585c18bf8b034f83c7034567a036625f099c8c1cb`）的 `requireApproval` 只有 `onResolution`，没有返回可拒绝执行结果的 `beforeExecute`。执行文件 `dist/agent-tools.before-tool-call-WtmCO7BO.mjs`（SHA256 `809c4545e65460961c9cb3e43fcfa506a4829c1a0f6c83889b689ff266903274`）对 `onResolution` 的 Promise 只附加错误日志；允许分支不等待该 Promise 即返回 `blocked:false`。包内也没有 SIQ 使用的 `approvalExecutionRecheckVersion` 能力标记。SIQ 适配器在这种宿主上拒绝 hold 是正确的 fail-closed 行为。

仓库里的固定宿主检查点补丁只适用于指纹钉住的 **2026.5.12**，不能套到 2026.9.4。若要把新版作为正式宿主基线，应先取得上游支持的最终参数、可等待且可拒绝的执行前检查点，或设计单独受控启动兼容层；随后在隔离配置中验证批准后单次效果、撤权、参数漂移和故障，再规划 Node 与宿主配置迁移。当前 LX03 仍为 `partial`，不因版本更新或基础链路 19/19 而升格。
