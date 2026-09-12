# M59：用户登录启动入口

日期：2026-09-12。codex/personal-client-upgrade-recovery 本地增量。

## 实现

service-login --enable --confirm-enable / --disable 在签名 unit、manager 归属及生命周期锁下，只创建/删除当前注册目录 default.target.wants/<实例名> 的精确符号链接。无 broad enable/disable，未知对象或异目标不操作；目录同步、reload 后读回。启用不启动或重启，关闭不停止当前进程。禁用中断后只复验/继续 reload，不重新接管其他对象。

verifyUserUnit 接受 enabled/ enabled-runtime 时同时核验精确自启链接；setup、状态、升级恢复等使用统一 scope 判断。注销要求先关闭自启，避免保留旁路入口。注册成功文案改为保留现状，不再错误宣称已启用服务未自启。

## 验证

- Go 全量、vet、CLI race、四目标构建与 diff 检查通过；最后仅注册提示文案更新后重跑 CLI 测试与四目标构建。
- 核心正负向：启用与重复启用、精确关闭、reload 失败后恢复、保留其他启动入口、已有普通用户对象拒绝覆盖/删除。
- 隔离 Linux runtime 实测：完整 setup、ui --print、自启入口启用、service-status、enabled-runtime 下重复 setup 保持 PID/config、关闭入口仍保持 PID、回到 linked-runtime，清理通过。原生运行 1.68s。
- 原生证据对应 Linux arm64 摘要 98558c96e5318c42696224096a01a7e107cb0328c2a03a55391e9e1135e18c99；其后只更新注册提示文案。最终开发构建摘要见下表。

| 最终构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 9fb29594b41b02cc49c38b08705ffd82c09a001faf664f618ba4e952c64bd024 |
| linux/amd64 | 6e94390318c5cd87d4a7c3869ff0396048f2cbb2832ccf455bb5bc8bfe4a2c96 |
| darwin/arm64 | 72d547435ea956d8a48c71eca060c3fac3e81ae819ea870c746f0615d11980d2 |
| windows/amd64 | 244459fca142f74d42a55443b94986b5b4210d81a373159ca3ab1d52ca32cf74 |

## 边界

仅临时注册范围实测，没有修改用户生产服务、退出登录或重启机器。真实持久用户登录后自动启动尚未验收；Windows/macOS 自启尚未实现。本批不代表三系统生命周期完成。runtime 入口仅本登录会话有效，不承诺下次登录存在。
