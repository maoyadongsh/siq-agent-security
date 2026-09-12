# K002 原生生命周期假设验证发现（ADR-050 假设核对）

日期：2026-09-12；执行环境：Ubuntu 24.04.4 LTS arm64（systemd 255.4，XDG_RUNTIME_DIR=/run/user/1000）；候选 `32b086ec18e15ead1e4c39a076e0863a22e5ccf2`，二进制 sha256 `897ec40be05cf60a2c8235457106bf79f3d8f0797dc657149a9057531fce9307`。全部实验在 `.tmp/` 隔离状态目录与非用户端口进行，未修改任何正式启动配置，未安装产品级后台项。

## 1. 各系统用户级后台机制（本机实查）

| 系统 | 机制 | 本机核实结果 |
| --- | --- | --- |
| Linux | systemd 用户服务 | 机制存在：`systemctl --user` 可用（本机报告 degraded，说明用户管理器在运行但有失败单元，机制本身可用）；`~/.config/systemd/user` 存在；本用户 `Linger=yes`（注销后用户服务可继续运行；未开 linger 的主机默认注销即停，需在文档中区分） |
| Linux | XDG 桌面自启动项 | `~/.config/autostart` 与 `/etc/xdg/autostart`（本机 56 项）约定可用；仅登录桌面会话时触发，不适合作为唯一后台保活手段 |
| Windows | 用户任务计划 | 本机无法验证（无 Windows 环境），保持 environment_unavailable |
| macOS | 用户 LaunchAgent | 本机无法验证（无 macOS 环境），保持 environment_unavailable |

## 2. 候选二进制的隔离生命周期行为（实测）

| 假设 | 实测 | 结论 |
| --- | --- | --- |
| 裸状态目录直接 serve 可启动 | 失败：`runtime_identity_invalid`（未先建 config.json；LocalDaemon/start-local.py 均会先写配置） | 启动前置条件对普通用户不直观；UX-003 安装器必须负责生成初始配置，错误消息需可读化 |
| 状态目录实例关联（ADR-050 §2 开放缺口） | 用状态目录 S2 对 S1 的端口执行 `status`：返回 ready（local-service-health/v1 只含 product/version/local_mode/status） | 确认缺口：健康协议不携带实例/状态目录身份，「同端口另一状态目录被复用」当前无法被识别；需新合同字段，本批不实现 |
| 双启动/活跃锁 | 同状态目录第二次 `serve`：退出码 1，报「write lock held by another process (pid …)」，活跃锁未被触碰 | 符合 ADR-050 第 3 条方向 |
| 优雅停止与重启 | SIGTERM 后同状态目录重启成功，`verify` 回执链完整（verified: true） | 状态在重启后保持 |
| 关闭浏览器不退出服务 | daemon 为独立进程，UI 仅经 embed HTTP 提供；实验全程无浏览器进程关联，服务持续 | 构造上成立（无浏览器耦合点） |

## 3. 确认的与未确认的假设

- 已确认：Linux 用户级后台机制（systemd 用户服务 + XDG 自启动）在本机可用；写锁、停止/重启语义符合设计方向。
- 未确认：Windows 用户任务与 macOS LaunchAgent 的权限/路径/登录注销行为（缺环境）；`status` 实例关联能力（确认缺失，待合同与实现）；裸目录启动报错的可读性；卸载归属的实机验证。
- 不确认范围扩大：本批不实现安装器/托盘/受控启动/原文存储/团队服务；ADR-0048 保持提案未实施。

## 4. 下一步最小实现建议（交审阅方裁决）

1. UX-003 首个增量优先做「安装器生成初始配置 + status 实例关联字段」：健康响应加入状态目录摘要或实例 ID（新合同字段），`status` 对不匹配者明确报错。
2. Linux 后台首版用 systemd 用户服务（本机 linger 已开），XDG 自启动仅作桌面会话内的补充入口；两条路径的卸载归属规则先写入合同。
3. 裸启动错误消息改为引导性提示（指向初始化/安装流程），不改动状态目录安全语义。
