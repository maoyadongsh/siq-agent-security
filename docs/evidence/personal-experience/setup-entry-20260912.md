# M56：Linux 首次后台启动整合

日期：2026-09-12。codex/personal-client-upgrade-recovery，本地开发增量，未发布。

新增 setup --confirm-setup [--port N] [--runtime]，串联既有初始化、签名用户服务准备/注册、启动和目录健康检查。已运行实例通过签名 unit、manager PID 和 scope 核对后复用，不申请主 Writer、不重启。成功显示实际管理 URL 和 pair 提示，无凭据进 URL。无确认/无效参数/非 Linux 在状态写入前拒绝，用户 systemd 不可用在初始化前拒绝；部分失败保留步骤供复验重试。

## 验证

- Go 全量测试、vet、CLI race、四目标构建与 git diff --check 通过。
- 参数负向验证未创建状态目录。
- 完整构建 CLI 在独立临时状态、空闲端口和 runtime 用户服务中实测：首次 setup → 正确管理 URL → API/manager 就绪 → 重复 setup 保持同 PID 和原 config → 不同注册 scope 拒绝；签名归属核对后清理。
- opt-in 命令：SIQ_TEST_SETUP_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m56-build/siq-linux-arm64 go test ./cmd/agentshield -run 'TestNativeSetupAndReuse|TestSetupRequiresConfirmationBeforeStateCreation' -count=1 -v。

| 最终构建 | SHA-256 |
| --- | --- |
| linux/arm64 | af1698eaaab1a126212a43cac5470ac59ca3a76ba1b4e89a8104910a294a881c |
| linux/amd64 | a8db9431a71075c743579d44d1703945dccceefa40f206c603d6c8bfe07b1bba |
| darwin/arm64 | 2a5a727a14be3ce324823dc4c75af41975c2eeebbbef22a19390b5a4c38adad2 |
| windows/amd64 | 07a77a2e13355c706ec795c1856d2274dd97e197361b5b4a91117d37f62b2ee9 |

## 范围限制

Linux 用户服务入口整合，不是正式安装包，不复制当前程序到固定安装位置；当前程序必须保留在稳定路径。尚无登录自启或自动打开浏览器，配对仍是独立命令。没有智能体权限自动激活或跨 OS 后台支持声明，UX-003/004/014 综合验收仍未闭环。
