# Hermes 按请求身份签发接线与回退说明

适用增量：E116。状态：安全端生产者组件已实现并通过本地测试；研究 API 客户端、真实守护进程联调及业务入口仍待接线。不是生产放行记录。

## 权限与部署边界

根 Runtime Identity 必须已经绑定有效、人工批准的 Grant 和当前可发现的 Hermes 实例。管理端显式登记固定企业 scope 的签发许可；此操作不能创建或批准 Grant。业务 API 仅持根 Runtime Bearer，沙箱只获得本次请求的子身份。签发、许可登记和请求取消路由不开放给沙箱 relay。

企业用户身份、租户、原业务授权、数据范围和执行租约仍由研究 API 核验。安全端只固定工具 Grant、企业 scope、请求 ID 和原执行摘要；客户端传来的执行摘要本身不证明企业授权有效。

## 版本化调用顺序

1. 管理端向 `POST /v1/runtime-request-issuers` 提交 `local-runtime-request-issuer-create/v1`。固定 `parent_identity_id`、`scope_id`、`max_identity_seconds`、`expires_at` 和操作人；单请求上限 60–3600 秒，许可不超过 24 小时且不能超过 Grant 截止。完全相同的重试返回原许可，不能原地修改 scope 或延长许可。
2. 宿主在核验原业务授权后，向 `POST /v1/runtime-identity/self/requests` 提交 `local-runtime-request-identity-create/v1`。请求 ID、原执行 SHA-256 和明确截止必须先固定并持久化，网络错误时只能用原正文重试。不得用新请求 ID 规避未知结果。
3. 响应为 `local-runtime-request-identity-issued/v1`，包含公开 identity Summary、request 绑定和私有凭据文件路径。身份继承根 Grant/instance/agent；HTTP 不返回密钥、credential_hash 或私有签名。客户端须验证固定 scope、request、执行摘要、期限和凭据路径/权限后再交付子身份。
4. 会话必须是 `siq:openshell:pool:<scope24>:<qwen-request-16hex>:siq_analysis:<64hex>`。服务端限制该前缀，子身份不能接管根身份或其他请求已登记的会话。会话期限不会晚于请求身份期限；重试不续期。
5. 停止或启动结果未知时，宿主向 `POST /v1/runtime-identity/self/requests/cancel` 提交原 request/execution 的 `local-runtime-request-identity-cancel/v1`。即使根身份或 Grant 已撤销、许可过期，正确根凭据仍可执行该清理。未发行返回 `issued=false`，同时保留取消记录，拒绝迟到发行。
6. 已交付子身份也可调用既有 `/v1/runtime-identity/self/revoke` 仅撤销自己。身份撤销不替代 OpenShell/systemd 停止、模型/数据撤权、Provider 恢复和原业务租约收尾，必须继续按请求生命周期执行。

所有时间使用 UTC、整秒、`Z` 后缀。根凭据、子凭据和管理会话不得写入命令行、普通日志、证据文件或版本库。

## 故障与重试

签名 attempt 先于秘密和签名发行记录发布；只有最终签名发行记录能够认证。发行前中断的原尝试可续接，不能修改期限或执行摘要。已经发行但凭据文件丢失、损坏、权限过宽或变为符号链接时失败关闭，不自动重建秘密。

取消先追加签名取消记录，再追加普通身份撤销。第二步失败必须报告未确认；第一步仍持续阻断认证和迟到发行。保留原材料后重试或按私有状态恢复流程处理，不能删除取消记录来“修复”任务。

各记录只追加或新建。身份保留原 512 条上限，attempt/cancellation 也有 512 条库存上限；满额后新请求拒绝，已有相同请求仍可幂等读回。当前没有自动归档，不能把该组件宣称为无限容量的生产签发服务。

## 回退

本轮没有替换活动 AgentShield、重启研究 API、启用默认 selector 或启动模型/沙箱。交叉编译制品独立存于 `var/flagship/e116-runtime-request-issuer/cross-builds-v1/`，不覆盖原制品。

后续试运行先停止新准入，使用支持 v3 的版本撤销本次子身份及根许可对应身份，并完成运行面清理。旧版本不识别新签名 `local-runtime-identity/v3` 记录，不能直接对含 v3 历史的状态目录做原地降级；需要保留匹配的新版本用于读回和清理，或按既有隔离状态切换流程回到独立旧状态。不能删除历史记录以使旧版本通过检查。

## 验证范围

已验证：严格 HTTP 合同与管理权限、原 Grant 继承、根/子隔离、独立请求会话、父撤销联动、期限边界、请求取消先行、并发与幂等、孤立秘密恢复、容量边界、签名但畸形记录拒绝、中继不转发宿主路由、Python/Go 规范签名样例对等。

本轮测试使用临时状态目录、合成批准夹具和 Go HTTP handler。尚未验证新制品的独立守护进程、研究宿主客户端、真实 OpenShell 子身份交付、API 重启扫描或企业 IAM/审批。交叉编译不是四平台运行验收，DGX Spark 原生发布门禁仍未放行。
