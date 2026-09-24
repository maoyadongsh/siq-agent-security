# 固定源码 API 的宿主连接与恢复器检查（2026-09-24）

本批完成宿主连接十项检查、恢复器五项检查，定位了正式部署仍需处理的 AppArmor 连接约束。主 API、既有权限及代理服务未替换，不将诊断环境通过记作生产部署完成。

## 宿主连接

固定源码 API 使用既有受控镜像、原绝对路径及只读 Python/venv。镜像自身没有 Docker、systemctl、systemd-run、SSH；补充本机这些程序和对应 ARM64 动态库的只读挂载后，程序可执行。

进一步只读挂载宿主 passwd/group，使 SSH 能识别实际 UID 1000；沿用当前用户的 Docker socket 组，连接既有 Docker socket 与用户级服务管理 socket。主 API 身份通过 PID/InvocationID 比对确认，不仅检查命令退出码。

默认 `docker-default` AppArmor 配置下，用户级服务管理查询返回 Access denied。单独的一次性诊断容器设置 `apparmor=unconfined` 后，下列检查全部通过：

1. Docker CLI 可执行。
2. systemctl 可执行。
3. systemd-run 可执行（仅版本查询，未创建服务）。
4. SSH 可执行（仅版本查询，未连接远端）。
5. OpenShell 可执行。
6. Docker daemon 连接成功，Linux ARM64 身份匹配。
7. 用户服务管理读回现有主 API 的准确 PID/InvocationID。
8. OpenShell 实际网关沙箱列表为空。
9. 实际运行身份经业务端严格 Self 合同验证通过。
10. 容器内原路径的 1,637 个固定文件与清单摘要全部一致。

该容器是受信控制面的诊断环境，访问宿主 Docker 与服务管理接口，不是承载不可信智能体的隔离沙箱。它采用 host network/PID 视图、只读文件系统、UID 1000、cap-drop ALL、no-new-privileges；`unconfined` 仅用于定位本次拒绝。没有停用宿主 AppArmor，没有更改任何已运行容器配置或 OpenShell 策略。正式服务若需要相同连接，仍须明确其运行方式及约束；本批不宣称默认 Docker 隔离下全部可用。

## 恢复器与唯一主进程

恢复检查使用独立 PostgreSQL 恢复库。源为上一批私有备份，SHA-256 `a072906cffc36cf353f6e29eeb85c4c7b2d747a7d81df46e9d334394f7e208ce`。该副本包含实际迁移结构，但没有本次可执行的 qwen-request running 任务。

只为现有两把锁提供原路径的文件级可写挂载，其他宿主材料保持只读：

- `var/openshell/canary/siq-analysis/pool/api-recovery.lock`；
- `var/openshell/qwen38/scoped-sandbox-proof/.owner.lock`。

检查结果：

1. 产品的真实 `_acquire_process_lock` 拒绝第二个 legacy 恢复器；没有调用接管或绕过原主进程的锁。
2. 请求恢复器对独立库执行首次扫描并进入 ready。
3. examined/deferred/released/failed/replaced/foreign 均为零，没有接管、续期、释放或重放业务请求。
4. 请求恢复器停止后 ready 为 false，后台 task 清理。
5. 网关 owner 前后均为空。

这是管理器在已声明的独立库中的真实启动/停止检查，没有在新 HTTP 服务上伪造 readiness，也没有把环境端口变量当作已经部署主 API 的证据。原主进程仍持有其恢复锁。演练数据库已删除，诊断容器均使用 `--rm` 退出。

## 未通过尝试与后续动作

保留最初缺少宿主工具、SSH 缺 UID 映射、默认 AppArmor 拒绝服务管理等诊断结果。无密码 sudo 和无特权 bwrap 命名空间也均不可用；未修改系统 UID 映射或全局安全配置。

下一步是确定并验证受信 API 的服务管理连接约束，然后实施主端口切换与恢复。报告工具权限仍等待[具体变更单](business-runtime-permission-plan-20260924.md)的答复；真实业务身份、审批、正式发行和原任务平台门禁未关闭。

本批[脱敏证据](../evidence/flagship-optimization-20260921/api-host-runtime-readiness-20260924.json)由 `var/flagship/api-host-runtime-readiness-20260924/candidate.json` 引用。私有环境、命令保存、完整日志和备份不公开。
