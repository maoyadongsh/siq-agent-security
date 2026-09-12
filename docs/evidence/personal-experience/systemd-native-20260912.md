# M40 Linux 用户服务原生验证

基线 a195fab + M35–M40 未提交工作区。系统 Linux arm64、systemd 255.4-1ubuntu8.15，用户管理器可用但总体 degraded（既有单位状态，不修改）。

## 结果与命令

最终候选执行：

```bash
# apps/control-api
SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m40-build/siq-linux-arm64 uv run pytest ../../scripts/personal-experience/test_systemd_user_service.py -q -o addopts=''
uv run ruff check ../../scripts/personal-experience/test_systemd_user_service.py
# apps/agentshield
go vet ./...
go test ./...
go test -race ./cmd/agentshield
```

原生集成 1 passed；包含独立 runtime-only link、服务启动和健康、重复启动保持 PID、CLI start 复用、restart 换 PID、配对成功、实例和配置不变、stop 正常成功、writer 释放、disable 清除链接。Go 和 lint 均通过；未变 Go 包有缓存。四目标构建成功。

测试仅复制可信构建到临时目录，选择随机端口和随机 unit 名称，未 enable 登录启动。二进制路径含空格/百分号；状态目录含空格、美元符号、百分号和引号，实际服务访问对应目录。测试配对输出只保存在进程内，不打印或写日志。

首轮因 FragmentPath 返回 /run 链接导致归属判断过严，未启动服务；核对链接目标和 MainPID=0 后清除自建链接，改用 resolve 后核对。第二轮发现 systemd 将双引号二进制路径视为 bad-setting，未启动服务；已修复导出提前拒绝，并清除自建链接。最终测试通过后 `systemctl --user list-units 'siq-lifecycle-test-*' --all --no-legend --no-pager` 无残留。

## 最终构建 SHA-256

| 目标 | 摘要 |
| --- | --- |
| linux/arm64（真实 systemd 运行） | a91e51343266dce6e0e6b98eaf897f7c68bbaae9e7763b9493fde7c12ce2f946 |
| linux/amd64（交叉构建） | bf8c7b7f47855ff51c8d06885f187716b1beba588b58942faf1eb57fea142dc5 |
| darwin/arm64（交叉构建） | 75954bbcc2b2281f34a809743d7350dfb6fa2ab34bf2090c417a72c8150f0c4b |
| windows/amd64（交叉构建） | 0c8a582afb1dc3edf6a8f76deb699e77980dde920e241768b18b543a916c1873 |

后台由原生 systemd 托管已实测，但产品自动注册/卸载尚未实现。未验证注销、重启主机、强杀、安装迁移、其他 OS 服务或智能体平台；不能据此关闭 UX-003/014/015。回退源码不改变历史事实，测试无正式配置需要回滚。
