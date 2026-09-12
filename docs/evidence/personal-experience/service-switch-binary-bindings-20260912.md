# M52：切换日志程序摘要合同与状态实现

日期：2026-09-12。分支：codex/personal-client-upgrade-recovery；基线 main 69d9c59，加本地 M48–M52 增量。开发制品，不是正式发行。

## 范围

- 新 local-service-switch/v2 合同将 source_sha256、target_sha256 纳入本地 Ed25519 签名。
- 新 PrepareServiceSwitchWithBinaries 严格拒绝空、非小写、非 32 字节摘要；原入口保持 v1，原样例未修改。
- 读取/应用 v2 复用原实例、目录、unit 摘要与配置事务恢复；篡改摘要、缺失绑定和版本混用拒绝。
- Go 生成固定规范化签名样例，Python 同时校验 v1/v2 Schema、签名和 unit 摘要。

## 验证

- Go TestServiceSwitch 系列通过：v1 故障恢复与漂移、v2 创建读取和重复应用、非法摘要无 pending 副作用、摘要篡改拒绝、版本/必需字段拒绝。
- Go `go vet ./...`、`go test ./...`、`go test -race ./internal/state` 通过。
- Python 合同 157 项通过；相关 ruff 通过。
- 四目标交叉构建通过，摘要如下。

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64 | c743b0a4035f8114a09fabfb6554ddbeb56726f1f731171c2bf22a219f841dcd |
| linux/amd64 | 18f28257449c22837272c4282d3eafdb6e5f3e61069a120f1ac5b5f1f0489930 |
| darwin/arm64 | d6a33141c0e459961a7fef06dc56d93e4eefa6dede4125b1e44734d49f8eb514 |
| windows/amd64 | 3bbcdf8db59fa3b15837f1e2a9f3a5917551f885dd65ec0554b49800b18930d8 |

## 边界与下一步

底层签名调用者传入的摘要，不读取程序、不验证发行信任，也不证明 daemon 内存映像。当前 CLI 仍调用 v1 创建入口；下一批须将当前快照、新候选摘要及停止/启动前的文件复核接入升级和回退，不能把本批合同测试描述为已经阻断 CLI 历史版本替换。未新增 systemd 原生或跨 OS 实机证据。任务 UX-003/014 仍未完成。
