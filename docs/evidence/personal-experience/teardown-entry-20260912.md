# M60：保留数据的后台退出流程

日期：2026-09-12。codex/personal-client-upgrade-recovery 本地增量。

## 实现

teardown --confirm-teardown 在生命周期锁中核验签名 unit、拒绝未完成切换，精确关闭自启、确认正常停止、获取主 Writer 后再次核验并注销注册。重复运行仍核验 manager 不存在和无活动写入。保留原程序、源 unit、配置、身份和历史，不卸载智能体钩子；提示停止后 block 受控操作拒绝。

已删除注册链接但 reload 中断时，只在正常停止且没有自启入口的前提下继续既有注销读回恢复，不删除其他对象。不强杀故障进程，不删除未知注册或绕过活动 Writer。

## 验证

- Go 全量、vet、CLI race、四目标构建与 diff 检查通过。
- 确认缺失/多余参数不写状态；无注册但活动 Writer 时不能宣称已退出；外来 source 拒绝。注册链接已移除后的 reload 故障重试成功，原 config 保持，定向 race 通过。
- 完整 Linux CLI、隔离 runtime 实例：setup → ui 地址 → 自启启用 → 状态/重复 setup 同 PID → 关闭自启同 PID → 再启用 → teardown → 重复 teardown → manager 无注册/数据与签名源保留 → setup 再次启动 → teardown 清理，全部通过（2.96s）。
- 未执行真实用户退出登录/重启，也未进行 Windows/macOS 后台验收。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 02d12cf22a69a684f104ebaae13549b1937fb6f41e7ecd30e7771bcd8f8582d7 |
| linux/amd64 | c93b56f1b4c0337ef941d4b10c377c34b84bfd1faa4218f2af3be6e73b4c05ae |
| darwin/arm64 | 5a8aebe531a3b72ba27455cb732fbd8771cecc3d8452eda0265fc99b7a65e8f5 |
| windows/amd64 | c60b7ae8aa56a9af9fd245b69377cc80229f1a29d5b0034d5e1c02294b6cdd28 |

个人安装生命周期在 Linux 的命令链已扩展，正式制品安装、跨版本和跨 OS 验收仍未完成；UX-003/014 不标 complete。
