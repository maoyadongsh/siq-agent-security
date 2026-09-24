# Linux OpenClaw 受控启动研究入口（2026-09-19）

当前本机实际 CLI 为 `OpenClaw 2026.9.5 (ec9c1a1)`；2026.5.12 与 2026.9.4 保留为历史固定档。SIQ 的批准后执行复查需要宿主执行前检查点，三版库存宿主都没有 SIQ 所需的最终参数复查合同。本仓库的 `scripts/openclaw-controlled-start.py` 支持经摘要固定的 **2026.5.12**、**2026.9.4** 和 **2026.9.5** 兼容配置：将自包含包复制到新建的 0700 私有目录，在副本应用对应固定补丁，并核对完整复制体摘要；它不会改写已安装的 OpenClaw 或复制真实用户配置。2026.9.5 还必须通过 [库存/受控兼容清单](../patches/openclaw/compatibility.v1.json)，仅版本号一致不能进入受控档。

在独立的 0700 目录下运行：

```bash
python scripts/openclaw-controlled-start.py prepare \
  --source /path/to/openclaw-2026.9.5-package \
  --destination /path/to/private/controlled-runtime \
  --node /path/to/node
python scripts/openclaw-controlled-start.py inspect \
  --runtime /path/to/private/controlled-runtime
python scripts/openclaw-controlled-start.py run \
  --runtime /path/to/private/controlled-runtime \
  --profile-home /path/to/private/profile-home \
  --node /path/to/node -- --version
```

`profile-home` 必须是另建的 0700 目录，包含已配置的 SIQ OpenClaw 插件、与仓库适配器摘要相符的 `index.ts`、回环 SIQ endpoint、`enforcementMode=block` 和仅本用户可读的凭据文件。入口拒绝真实账户 HOME、未知包版本、宿主目标摘要变化、插件未启用、非回环 endpoint、非 block 模式、兼容清单漂移及复制体被篡改。2026.9.x 源目录须包含完整依赖；2026.9.4 历史验收使用 Node 24.18.0，2026.9.5 当前验收使用 Node 24.21.0。`run` 使用指定 Node 和该隔离 HOME 启动；它**不是操作系统沙箱**，也不能替代用户设备上的安装、升级、回滚和外部效果原子性验收。

本机定向检查：`prepare`、`inspect`、隔离配置下 `run -- --version` 成功；篡改复制体后 `inspect` 拒绝。[新联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-start-ui-hold-summary.json)使用本入口的 `prepare` 和 `inspect` 生成副本，再由现有真实原生宿主 harness 从该副本启动网关；内嵌 SIQ 页面批准后执行一次，拒绝后零执行。该腿尚未通过本入口的 `run` 子命令启动网关，也不能证明原版宿主具备此检查点。LX03 保持 `partial`。

[托管原生 CLI 联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-start-managed-native-summary.json)另以 `prepare` 后的副本通过本入口 `run` 实际启动 `openclaw agent --local`，使用产品 managed adapter 安装生成的隔离配置与凭据。22 项检查通过：原生会话登记、授权读取、无权限写入和有效 Grant 下的目录外读取拒绝、按任务原文采集与撤权、身份吊销、七条签名回执。验收驱动只向该 CLI 子进程注入了错误的旧版端点/模式、SIQ 模式、OpenClaw 配置路径以及无效 Node 预加载/模块路径；链路仍通过，证明这些继承变量没有覆盖受控配置。此腿使用合成模型和无害 fixture，不包含浏览器审批，且不使原版宿主审批检查点变为可用。

历史 OpenClaw 2026.9.4 先在隔离 Node 24.18.0 环境中完成[基础链路和原版 hold 负向评估](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-upgrade-assessment.md)，随后使用独立、按新版目标摘要固定的补丁完成[受控审批链](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-approval-summary.json) **18/18**：原版安全拒绝 1 项，普通审批 6 项、撤权 2 项、故障与参数变化 9 项全部符合预期，回执链验签。启动器的 `prepare`/`inspect`/`run -- --version` 已在 2026.9.4 自包含副本与 Node 24.18.0 上通过，旧 2026.5.12 配置也在重构后完成完整审批链回归 **18/18**。另以同一隔离安装通过受控启动器实际运行 2026.9.4 公共 `openclaw agent --local`，产品托管安装、原生会话、授权读取、目录越界拒绝、原文撤权、身份撤销与七条签名回执共 **22/22**。该轮两版补丁不能互换；结果是临时受控副本，不等于上游原版能力、默认升级、正式发行或外部效果原子性证明。当时本机 2026.5.12 安装保持不变。

2026-09-21 的 OC-01 已在实际 2026.9.5 包和 Node 24.21.0 上重新建立独立档位。库存同名业务工具 hold 在平台审批前失败关闭；受控副本通过普通审批、撤权、回调故障、最终参数变化及 BU-01 报告发布工具共 **20/20**，46 条回执链验签。启动器 `prepare`、`inspect`、`run -- --version` 与清单篡改拒绝通过，库存目标文件摘要在验证后不变。详情见 [OC-01 脱敏证据](evidence/flagship-optimization-20260921/oc-01-openclaw-parity.json)。三版补丁互不兼容；2026.9.5 结果仍是私有临时副本，不代表上游原版、生产发行或真实外部效果原子性。
