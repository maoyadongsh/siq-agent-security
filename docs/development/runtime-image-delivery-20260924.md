# 业务沙箱镜像切换与主 API 准备（2026-09-24）

已将当前 Qwen 请求沙箱镜像指向真实报告交接 v8 使用的候选，并实际完成新→旧→新回退演练。主 API 保持原进程；请求级执行切换仍待实际权限与业务身份验收。

## 已生效的变更

研究仓 `var/openshell/qwen38/candidate-image/current-image.json` 现指向：

- 新镜像：`sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02`。
- 原镜像：`sha256:5a45f0d98c0c86d57d601dc1a7d2bcd99d36e2b9e9c05cb6d94527cebe5548ac`。
- 新记录 SHA-256：`c7d9fa3528622b71fb89a4e7dfe14369dffcc89b365531114dca4e38308f591f`。

镜像由现有 `verified_candidate` 验证文件权限、路径、基础镜像、配置与源码标签及实际 Docker image ID。实测来源为真实报告交接 v8，证据 SHA-256 为 `9e9107692db14e40a6b280b46c57870c85f8d25f9f4c6b734302899f9108295d`；不重复已经通过、没有源码变更的模型调用。

切换持有现有 Gateway owner 锁；确认 owner 为空、网关无沙箱后，以 0600 同目录临时文件、fsync 和原子替换写入指针。新→旧→新每一步均调用产品验证器读回。镜像记录仍保留 `production_eligible=false` 及其原有离线验证声明，实际模型证明由独立 v8 证据提供，不改写历史元数据。

未启动业务执行。主 API、新预览 API 与 Web 的 PID/InvocationID 均未改变。当前主 API 仍采用旧 `legacy` 请求配置，因此镜像指针更新本身不代表请求级报告功能已经在主 API 开放。

## 主 API 部署准备

已从仍运行的主 API 精确进程取得环境，私有保存原配置及待应用配置。待应用项为 `qwen38` 请求后端、`confidential_local` 数据级别、host 部署模式，以及保持必需的恢复门禁。没有设置隔离测试镜像例外，没有关闭 required 或伪造 ready。

已核对当前预览使用的 994 项 Python/安装包源码摘要，生成完整归档并逐项读回验证。归档 SHA-256：`4c269900b7d62ac8323b45c3b119d159d9fea17f7bbf380471d6c529356213c4`。

这些材料位于研究仓 `var/ops/main-runtime-delivery-20260924/`，包含真实环境和受控源码，不公开。该归档是已经测试的当前预览源码，**不是原主 API 的历史源码快照**。原主进程来自持续变化的工作区；目前不能声称停止后能原样冷启动。因此本轮没有为了显示“已切换”而停止原主进程，主 API 切换仍需形成明确的恢复方案。

## 当前权限缺口与具体变更单

宿主升级后的严格身份校验已通过，但原 grant 只含 `read_file`、`terminal` 和旧的公司分析目录，没有固定报告工具。扩大授权不能由镜像升级推导。

已准备[江淮汽车样板权限变更单](business-runtime-permission-plan-20260924.md)：新增固定报告工具，读取限定公司与公共元数据，写入限定请求输出目录，使用原业务代理；以该公司 scope 的独立新绑定保留旧绑定回退。已向用户请求明确授权，尚未收到答复时不签发、不批准、不应用。真实业务账号、独立复核员权限和生产身份验收继续独立保留。

## 镜像回退

原记录保存在研究仓 `var/ops/main-runtime-delivery-20260924/previous-image.private.json`；新记录另有受控副本。回退应使用同一 Gateway owner 锁，确认无 owner/沙箱，复验当前指针仍为本批新摘要，再以同目录 0600 临时文件原子发布原记录并调用 `verified_candidate` 确认旧镜像。不得重复运行本批一次性脚本覆盖证据；不得在活跃请求中途换指针或借回退覆盖其运行快照。

本批[脱敏证据](../evidence/flagship-optimization-20260921/runtime-image-delivery-20260924.json)由同批 `var/flagship/runtime-image-delivery-20260924/candidate.json` 引用。原总目标仍未完成，正式签发、企业联调、原模型和原生平台门禁没有被本次部署准备替代。
