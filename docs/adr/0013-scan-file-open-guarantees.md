# ADR-013：扫描读取的打开保证与残余 TOCTOU

- 日期：2026-09-06
- 状态：已采纳（DEV05-C）
- 范围：`apps/agentshield/internal/admission` 与 directory connector 的有界文件读取；不覆盖同 UID 对抗进程的完整 OS 隔离，也不替代发布 staging（DEV04-D）。

## 背景

DEV05 要求：打开前拒绝非普通文件；打开后再次验证类型与身份；有界读取；处理检查后替换。仅用 `Lstat` 再无约束 `ReadFile` 不足。完整 race-free（例如 Linux `openat2`/`RESOLVE_BENEATH`、强制沙箱）与「标准库 + 跨平台」约束冲突时，须先写清支持保证，避免把前后 `Stat` 误称为 race-free。

## 决策

1. **打开契约（所有支持平台）**
   - 枚举侧先拒绝可静态识别的非普通文件（FIFO/设备/socket/目录等）。
   - 打开后对 **已打开 fd** 做 `Stat`：必须仍是普通文件，且 `os.SameFile` 与打开前的 `FileInfo` 一致；否则受控错误（`file changed while opening`），不得继续读内容、不得发布 content hash。
   - 读取严格受剩余总字节预算约束，并用 +1 字节探测截断。

2. **Unix（Linux / Darwin 等，`unix` build tag）加强**
   - 使用 `syscall.Open`：`O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`。
   - `O_NOFOLLOW`：路径在打开瞬间是 symlink 时失败（典型检查后替换为链接），不跟随到目标。
   - `O_NONBLOCK`：FIFO 等特殊文件在打开阶段不无限阻塞；随后由 fd `Stat` 判为非普通并拒绝。
   - 仍 **不** 宣称：同 UID 攻击者在打开成功后改写已打开 inode 之外的路径、或替换目录项后再让扫描「看见另一棵树」时完全无窗口。

3. **Windows 与其他无 `O_NOFOLLOW` 平台**
   - 保留 `os.Open` + 打开后 `Stat`/`SameFile`。
   - 明确残余：检查后将普通文件换成 symlink/特殊文件仍可能存在窄窗口；完整边界需平台专用 API 或沙箱，另立任务与实机证。

4. **诚实对外**
   - `desktop-same-uid` 下，扫描加固降低 TOCTOU 与阻塞风险，**不等于** managed-linux / 沙箱证明。
   - 缺实机特殊文件/对抗证据时，不得把本 ADR 记为「整任务 DEV05 验收通过」。

## 验证

- 正：稳定普通文件树 HashDir/Admit 与既有预算行为不变。
- 负：FIFO 在有限时间内受控失败；直接打开 symlink 路径失败（Unix）；打开前 inode 与 fd 不一致时拒绝并拒绝 content hash。
- 不测项：同 UID 持续对抗下的零窗口；Windows 特殊文件矩阵（标平台缺口）。
