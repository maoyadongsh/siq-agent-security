# macOS Luke：历史 0.1.0 制品对 v2 状态的实际拒写失败

**这是历史制品的观察到的失败，不是 Mac-P03 拒写通过。** 从 [官方 `agentshield-v0.1.0` Release](https://github.com/maoyadongsh/siq-agent-security/releases/tag/agentshield-v0.1.0)取得 `agentshield-darwin-arm64`，SHA256 `7603b01294751fb2dca82a963f51c41468e745721180ba090bb842b1380127a8` 与该 tag 的 `skills/agentshield/skill-manifest.json` 固定值一致，实际 `version` 返回 `agentshield 0.1.0 (darwin/arm64)`。tag `f14bb06` 早于引入 N01 v2 屏障的 `9ba20e8`；源码没有状态格式兼容性检查。该历史制品不是任务书要求的“兼容感知、只认 v1 且拒绝 v2”的旧程序，不能用其年代或版本号补作该正向证据。

仍在完全私有的新目录做了真实负向演练：本候选先 `init` 出 format 2 状态，`state-status` 为 `compatible=true/status=ok`，原有文件仅 3 个；再在独立 HOME、`AGENTSHIELD_STATE_DIR` 与 47615 端口运行旧发行版 `serve`。旧程序**没有副作用前拒绝**，创建了 `keys/signing.seed`、`token` 和临时 `serve.lock`，并在 `127.0.0.1:47615` 实际监听。精确停止测试进程后端口释放、锁消失，状态文件由 3 个变为 5 个；format、instance、config 三个原文件摘要均不变，当前程序仍能只读诊断 format 2 为 compatible。脱敏的输入、摘要与结果见 [负向记录](legacy-release-v2-negative.json)。测试目录仅本机私有保留以供复核，私钥和 token 原值从未归档。

判断：旧 0.1.0 是 N01 兼容窗口外的历史可执行程序，已发布字节无法由当前源码补丁追溯变成“拒写 v2”。[N01 规格](../../../../n01-state-protocol-design-20260913.md)也明确“未实现检查的历史二进制不纳入直接运行保障”。Mac-P03 所需的**真实兼容感知 v1 源码/制品**仍未找到，因此对应正向验收保持 blocked；本次历史发行版演练另记 `observed_failure`，不可用 blocked 掩盖。不得把 0.1.0 作为 v2 回退目标，也不得向它传入生产 v2 状态路径。当前 v2 程序、日常状态和 47612/47613/47614 均未被旧程序触及。
