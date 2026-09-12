# M42：Linux 用户服务注册验证

2026-09-12，当前 `codex/personal-k002-platform-readiness` 未提交工作区，保留 M35–M41。规格 §3.11.6；签名配置合同沿用 M41，不新增服务运行状态合同。

`service-register [--runtime]` 持有 state Writer 准备并核对配置，再调用当前用户 systemctl。无 shell/force/sudo，单调用 15 秒超时、64 KiB 输出上限，原始错误输出不转发。要求已有同名单位 loaded、无 drop-in、FragmentPath 归属一致、linked 范围匹配；未知单位拒绝。link/reload 后再次读回，错误保留可复验材料，不谎报成功或盲目删除。

## 验证结果

- Go 全量、vet、CLI/state race 通过，gofmt 无未格式化文件。
- 单测覆盖首次注册、重复注册重载、同名外部文件、drop-in、masked、范围变化、字段缺失/重复，以及 link/reload/readback 失败；失败不调用回滚或启动。
- 四目标 linux/arm64、linux/amd64、darwin/arm64、windows/amd64 构建通过。
- `SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m42-linux-arm64 uv run pytest ../../scripts/personal-experience/test_systemd_user_service.py -q`：1 passed。Ruff 通过。
- 原生测试使用隔离随机实例及含空格/百分号/引号的状态路径，产品 service-prepare/register --runtime 两次成功；读回 linked-runtime、inactive、MainPID=0。拒绝将同一单位隐式切换为持久注册，原范围保留。之后实际 start/restart/pair/stop、身份/配置保留、writer 释放和 disable/reload 清理通过。
- 测试后的 `systemctl --user list-units 'siq-agent-security-*.service' --all --no-legend --no-pager` 无输出。未改变用户原有服务、未启用登录自启。

## 构建摘要

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `e00da58ede2217177bf7d3a06fcbf8921ea498e5f6a332c966d0da27734a223b` |
| siq-linux-amd64 | `f9f8c52f5f440370fba967e6477a11c9cb21a796ba0676fb6316abe0cab0ce28` |
| siq-linux-arm64 | `a8203d2c1fd838708f8cefd9667e5c8d5b64d5c09dd44f17a6867383a689a080` |
| siq-windows-amd64 | `b4f424c3c3bc9af3585f20e275254db74b9cdb7a2fa90e9730d68fdde0657c98` |

## 边界

原生证据只覆盖 Linux runtime 注册；默认持久 link 已实现，未在用户真实持久服务路径执行验收。启停目前由系统命令完成，产品启停/卸载/迁移与登录自启尚待实施；不能记为完整安装包或 UX-003 完成。Windows/macOS 仅构建，三系统/三平台及其他个人任务、LAN 目标保持 active。

systemctl 行为依据：[上游命令文档](https://github.com/systemd/systemd/blob/main/man/systemctl.xml)；本批实测以本机 manager 为准。
