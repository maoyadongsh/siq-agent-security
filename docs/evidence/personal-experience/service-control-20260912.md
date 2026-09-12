# M43：产品 Linux 服务启停与状态验证

2026-09-12，当前未提交工作区，继承 M35–M42；开发规格 §3.11.7。新增 service-start/service-status/service-stop --confirm-stop。

## 实现

只读加载已存在签名身份并验证配置记录、unit 字节和 manager 来源。status 不创建状态或恢复缺失文件。服务管理写操作共用 `service-control/serve.lock` 的既有 Writer 协议，独立于 daemon 主锁；不绕过业务状态单写者。start 读回 active/正数 MainPID 与目录健康绑定；stop 显式确认，正常停止须 inactive/MainPID=0/Result=success 且主锁消失，不删除残留锁或操作未知 PID。超时返回不完整状态，用户可再次查询。

## 验证

- Go 全量、vet、CLI/state/signing race 通过；gofmt 无输出。
- 负向：停止未确认不写、未初始化 status 不建目录、只读身份不生成密钥、主 Writer 持有时可验证、缺失 unit 不修复、异常 Result/PID/状态或残留 Writer 不报告正常停止。既有归属、签名和漂移用例继续通过。
- 四目标交叉构建通过，Windows/macOS 仍没有原生运行证据。
- 原生 `SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m43-linux-arm64 uv run pytest ../../scripts/personal-experience/test_systemd_user_service.py -q`：1 passed in 3.56s；Ruff 通过。
- 隔离 Linux systemd 用户实例：产品 prepare/register --runtime、重复注册、范围变更拒绝、service-start 两次保留 PID、未确认停止拒绝且 PID 保留、运行状态检查、确认停止/再启动（PID 变化）、pair、最终确认停止与停止状态检查通过。配置/实例不变、主锁消失；测试最终只清理已复验归属的 runtime 链接。
- 测试后 siq-agent-security-* 用户单位列表为空；未启用登录自启，未改变用户生产服务。

## 构建

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `d43c87cf5cc6d5951fcd498df7eec8214ca0e1c5d009afddb56d0c3f704cc8ca` |
| siq-linux-amd64 | `75478f96d710e03ffe2ed3390a7baa1526cb7a6bc870934611616dd23be16deb` |
| siq-linux-arm64 | `5d6a40872cd92b7cf8688562faf59714358357d273b9630e0efaf8c628cfa712` |
| siq-windows-amd64 | `0c7dd9b129aedc6f87ea37b3153405fc66435eb9e95dd62a2fb7a20f29e41b8b` |

完整 UX-003 尚未完成：产品卸载、注册范围迁移、二进制升级恢复、桌面入口和跨 OS 原生验收继续待办。状态输出为人类可读 CLI，未新增 Web 生命周期 API。本批正常停止证据不代表强杀/断电恢复已验收，完整个人/LAN 目标仍 active。
