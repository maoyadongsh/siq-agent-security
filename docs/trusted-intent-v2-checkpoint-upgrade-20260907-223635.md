# Trusted Intent V2：宿主检查点升级、回退与中断恢复

- 时间：2026-09-07 22:36，Asia/Shanghai。
- 基线：`87fd1ce` 加当前未提交增量。
- 交付：固定版本兼容工具、15 项回归测试、完整原生副本升级/回退验收及 CI 接线。
- 状态：本地验证通过；本机原安装与实际用户配置均未修改。

## 1. 工具职责

[openclaw-checkpoint-compat.py](../scripts/openclaw-checkpoint-compat.py) 为 OpenClaw 2026.5.12 的审批检查点 v2 提供 `inspect`、`apply`、`restore`。使用仓库中的固定 [补丁清单](../patches/openclaw/2026.5.12-approval-execution-recheck-v2.json)，不接受用户替换清单或模糊应用到未知源码。

| 操作 | 行为 |
| --- | --- |
| inspect | 只读检查包名、版本和目标文件；按字节指纹报告 stock、checkpoint-v2 或 modified，不创建备份或锁文件 |
| apply | 持有目标目录中的 POSIX 文件锁，持久化原始字节与恢复记录，生成并核对补丁后字节，再同目录原子替换；重试已完成替换可幂等收尾 |
| restore | 验证备份身份、原始字节、权限属主和完成标记；只恢复预期补丁后文件或收尾已恢复的原文件，拒绝覆盖后来改动 |

工具只处理宿主的一个已知 JavaScript 文件，不更新 SIQ 插件、不改平台配置，也不停止或重启任何服务。输出包含 `disk_only=true`；磁盘已修补不代表现有进程已经加载新代码。修改操作目前要求 POSIX 文件锁；Windows 修改路径明确拒绝，不能绕过锁使用。

## 2. 备份与写入协议

调用者必须显式提供目标安装路径和**位于安装目录之外的独立备份目录**。工具新建目录权限为 0700；既有备份目录须同样为 0700，并且不能混入无关文件或通过符号链接引用其他位置。

备份文件：

- `original.js`：与固定原始 SHA-256 相符的完整目标文件，权限 0600。
- `prepared.json`：目标安装身份、相对文件名、修改前后摘要，以及原 mode/uid/gid。
- `applied.json` / `restored.json`：只新建的完成标记；存在时验证内容，不能原地覆盖。

原始备份、准备记录和标记先写独立临时文件、fsync，再以排他链接发布并同步目录，避免半写的最终记录。目标内容写入同目录临时文件、保留 mode/uid/gid、fsync，重新检查原目标摘要后用 `os.replace` 替换并同步目录。进程中断可能留下工具自己的临时文件；它们不作为有效记录读取，不触发用户文件删除。

同一个目标使用固定锁文件及内核 `flock`，拒绝并发修改。强杀后内核自动释放锁；残留锁文件不是“操作仍在进行”的证据，也不要求按 PID 猜测后删除它。不要在使用中删除锁文件，以免产生不同的锁 inode。

这些记录是本地文件恢复资料，不是签名 Intent、业务授权审计或真人批准证明。文件锁协调本工具的调用，不能排他控制不使用该锁的包管理器或恶意同 UID 进程。

## 3. 操作说明

先停止目标 OpenClaw 实例，并避免同时进行 npm/其他安装更新。使用安装文件所属用户操作；权限或属主无法保留时工具失败退出。

```bash
python3 scripts/openclaw-checkpoint-compat.py inspect \
  --openclaw-root /path/to/node_modules/openclaw

python3 scripts/openclaw-checkpoint-compat.py apply \
  --openclaw-root /path/to/node_modules/openclaw \
  --backup-dir /path/to/private/new-checkpoint-backup
```

然后按平台方式重新启动。当前 SIQ 适配器也需部署到该实例；重新构建 SIQ 并安装插件不会自动执行上述宿主修改。应核对实际加载的版本与负向行为，不能仅以 `inspect` 的磁盘状态作为运行中能力证明。

需要回退时再次停止该实例，并使用同一备份目录：

```bash
python3 scripts/openclaw-checkpoint-compat.py restore \
  --openclaw-root /path/to/node_modules/openclaw \
  --backup-dir /path/to/private/new-checkpoint-backup
```

回退后重新启动。当前适配器在原版宿主上会因缺少能力标记而拒绝 hold；这是明确的兼容性行为，不等于回退后可继续完整审批。若回退之后需要再次升级，使用新的独立备份目录，保留旧记录。

### 中断后的处理

| 中断点 | 磁盘状态 | 可用恢复方式 |
| --- | --- | --- |
| 备份已完成，尚未替换 | 原始目标 + 准备记录 | 使用相同目录重试 apply |
| apply 已替换，尚未写完成标记 | 补丁目标 + 原始备份 | 重试 apply 完成标记，或 restore 回退 |
| restore 已替换，尚未写完成标记 | 原始目标 + 已有备份 | 重试 restore 完成标记 |
| 目标、权限、备份或完成标记被后来修改 | 与记录不一致 | 工具拒绝覆盖；检查具体变化，不通过删除校验或改摘要强制通过 |

## 4. 15 项回归测试

[test-openclaw-checkpoint-compat.py](../scripts/test-openclaw-checkpoint-compat.py) 使用合成包文件和临时目录，不依赖本机 OpenClaw 安装。覆盖应用/恢复与幂等、权限保留、新备份周期、目标后来修改、错误版本/补丁/产物摘要、损坏备份/身份/完成标记、权限变化、不安全备份目录、符号链接/硬链接和并发锁竞争。

三个中断测试在独立子进程中对自身发送 `SIGKILL`，分别命中准备完成后、升级替换后及回退替换后，验证目标字节、记录状态和重试结果。此证据属于进程强杀，不扩展为所有文件系统掉电或硬件故障保证。

```bash
python3 scripts/test-openclaw-checkpoint-compat.py
```

当前 15 项全部通过，已加入 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 的独立检查步骤。CI 接线是本轮未提交改动，尚未有对应远端 CI 结果。

## 5. 完整原生副本验收

[validate-openclaw-checkpoint-upgrade.py](../scripts/validate-openclaw-checkpoint-upgrade.py) 独立复制完整运行时，通过实际 CLI 执行 inspect/apply/重复 apply，然后启动原生网关验证正常批准与等待期间 Grant 撤销。原生进程关闭后，通过 CLI restore/重复 restore，再启动新的原生进程验证缺能力 hold 被拒绝。

| 检查 | 结果 |
| --- | --- |
| CLI 应用后目标字节等于 v2 清单摘要 | 通过 |
| 重复 apply 不再替换目标 | 通过 |
| 升级后的正常批准 | 执行一次，产生一条 observation |
| 升级后，Grant 在平台等待期间撤销 | 执行零次，observation 零条 |
| 两个升级场景的独立回执链 | 五条，HTTP 与离线验签通过 |
| CLI 回退与重复回退 | 原始字节精确恢复，重复操作无替换 |
| 回退后的新进程 | 当前适配器拒绝缺能力 hold，不进入平台审批或执行 |
| 回退场景的独立回执链 | 一条，通过验签 |
| 原安装、仓库适配器和原始备份指纹 | 验收前后核对一致 |

完整 [验收归档](evidence/intent-v2/native-openclaw-checkpoint-upgrade-20260907.json) 为 `passed=true`，最终入口退出码 0。记录真实 CLI 状态、源文件与 runner 指纹、备份摘要，以及升级前后各自的原生证据。

```bash
python3 scripts/validate-openclaw-checkpoint-upgrade.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/openclaw-checkpoint-upgrade.json
```

此命令只修改独立临时副本。验证使用重新启动的原生进程与合成会话，不证明热切换、真实用户会话迁移或生产环境部署完成。

## 6. 当前边界

宿主兼容工具及其中断恢复已经落盘并通过本地验证；实际安装仍未应用，配套检查点仍非官方上游能力。当前目标中的真实用户、消息渠道、CodeBuddy、完整旧版本兼容、独立复核和检查点后并发窗口仍未全部关闭。新增脚本 Ruff、CI pin 检查、文档与证据检查通过，本轮没有修改 Go/HTTP 合同或重跑无关全量测试。
