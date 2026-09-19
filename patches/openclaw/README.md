# OpenClaw 固定版本兼容补丁与受控实验

此目录保存针对已验证缺陷的候选补丁及固定源码指纹。它不是 OpenClaw 官方发布，也不会随 SIQ 安装器自动修改用户的 OpenClaw 安装。

## 版本与当前使用入口

| 宿主版本 / 材料 | 用途与状态 |
| --- | --- |
| [2026.9.4 检查点补丁](2026.9.4-approval-execution-recheck-v1.patch) / [指纹元数据](2026.9.4-approval-execution-recheck-v1.json) | 当前 Linux 双宿主实验的受控副本路线；审批后最终参数复验与检查点协议 v1 |
| [2026.5.12 检查点 v2](2026.5.12-approval-execution-recheck-v2.patch) | 历史原生集成、故障与回退实验；使用该版本对应指纹 |
| [2026.5.12 空闲重置](2026.5.12-idle-transcript-reset.patch) | 独立的 transcript 生命周期实验，不与审批修复混为一项 |

2026.9.4 的选择与运行按 [Linux 受控启动指南](../../docs/openclaw-controlled-start-linux-20260919.md)操作。元数据固定宿主文件、补丁和适配器摘要；仅版本号相同不够，摘要不匹配必须重新评审，不能模糊套用。受控副本的阶段结果见[评测索引](../../evaluations/README.md)，不代表 OpenClaw 上游原版或所有宿主已具备该能力。

这些补丁用于研究审批与执行之间的时序缺口：平台批准之后，仍要检查当前授权和最终参数，再由 SIQ 建立执行预留。它们不签发权限、不代替沙箱，也不自动获得对真实用户安装的修改授权。第三方原始许可见 [LICENSE](LICENSE)和[仓库声明](../../THIRD_PARTY_NOTICES.md)。

## 2026.5.12 历史验收

当时的适配器优先使用 `2026.5.12-approval-execution-recheck-v2.patch` / `.json`：v2 原生包装器增加检查点协议标记，当前适配器已直接包含执行回调，不再应用旧适配器补丁。`scripts/validate-openclaw-approval-integration.py` 使用实际当前适配器，在原版及配套临时宿主上通过 18 个场景。详见 [集成与兼容性说明](../../docs/trusted-intent-v2-approval-integration-20260907-221813.md)。以下 v1 配套文件与 runner 保留为历史实验，当前源码的指纹不同，旧 runner 会按设计拒绝应用。

新增审批等待期间撤销的配套候选：`2026.5.12-approval-execution-recheck.patch` 与 `2026.5.12-approval-recheck-adapter.patch` 必须配套，由 `2026.5.12-approval-execution-recheck.json` 锁定两侧指纹。详见 [原版失败与候选验收](../../docs/trusted-intent-v2-approval-revocation-20260907-220037.md)。`scripts/validate-openclaw-approval-recheck-patch.py` 仅在临时副本测试，已通过原有六个审批场景及两个撤销对照场景；本机原安装和默认适配器仍未更新。下文描述独立的空闲重置补丁，两者不应混为同一项验收。

## 问题和修复范围

OpenClaw `2026.5.12` 的本地 `agent --local` 空闲重置会轮换会话 UUID，却可能保留旧 `sessionFile`。后续会话解析因此继续把旧工具历史发送给模型。

补丁修改 `dist/agent-command-BQgTSh4F.js` 中两处会话条目更新：当旧 UUID 与新 UUID 不同时清除旧 `sessionFile`，并更新 `sessionStartedAt`；UUID 未变化时保留文件和起始时间。这样后续原生 transcript 解析器会为新 UUID 选择新文件，普通续聊继续使用原文件。

补丁仅验证了该版本的嵌入式 CLI 空闲路径。它不会删除旧文件，不会解除 SIQ 固定 Intent 绑定，也不改变 SIQ 污点或动作序号。

## 文件

| 文件 | 用途 |
| --- | --- |
| `2026.5.12-idle-transcript-reset.patch` | 两处会话更新的统一 diff |
| `2026.5.12-idle-transcript-reset.json` | 包名、版本、目标路径、修改前后及补丁 SHA-256 |
| `LICENSE` | OpenClaw 原始 MIT 许可；原版权属于 Peter Steinberger |

## 安全复测

从 SIQ 仓库根目录执行：

```bash
python3 scripts/validate-openclaw-idle-patch.py \
  --openclaw-root /absolute/path/to/openclaw-2026.5.12 \
  --node /absolute/path/to/node \
  --out /tmp/openclaw-idle-patch-validation.json
```

脚本先检查版本和源码指纹，再完整复制运行时到临时目录，在副本中执行 `git apply --check`、应用补丁、检查 JavaScript 语法，并运行真实 CLI/一分钟空闲重置测试。副本采用独立文件，不使用硬链接；整个过程不会把补丁应用到 `--openclaw-root`。版本或源码不匹配直接失败，不执行模糊应用。

运行需要 Go、Node、Git、Python 和约 0.5 GB 临时磁盘空间；包含一分钟真实等待及 CLI 启动时间。状态、日志和运行时副本在结束时清理。报告明确标记 `runtime_kind` 为打补丁的临时副本，不能将其中的结果归为原版 OpenClaw。

已验证：正常跨进程续聊、不同 key 的绑定隔离、真实空闲 UUID 轮换、新历史文件、旧工具内容不再发送，以及 SIQ 授权/污点/动作链保留。验证细节见 [补丁验收报告](../../docs/trusted-intent-v2-openclaw-reset-patch-20260907-204200.md)。

该次 2026.5.12 实验未对本机实际安装或上游仓库应用补丁，也未验证网关手动 reset、审批与消息渠道。若未来采用其他 OpenClaw 版本，应先复现并检查其源码，不能跳过指纹限制套用此补丁。

审批后检查点的 [九场景故障验收](../../docs/trusted-intent-v2-checkpoint-faults-20260907-220834.md) 使用 `scripts/validate-openclaw-checkpoint-fault-patch.py`，包括严格布尔返回、异常、五秒超时、取消、最终参数摘要拒绝与平台等待后失联；19 条回执恢复验签通过。与原版失败、候选八场景对照分别归档，默认安装仍未采用候选。

v2 宿主现有 [固定指纹升级/回退工具及 runbook](../../docs/trusted-intent-v2-checkpoint-upgrade-20260907-223635.md)：`scripts/openclaw-checkpoint-compat.py inspect/apply/restore`。修改需显式目标与独立私有备份目录；只支持 POSIX 锁，须停止目标实例、完成后重启。15 项恢复测试与完整临时副本原生演练通过，实际安装未操作；Windows 修改、热切换和用户会话迁移未验证。
