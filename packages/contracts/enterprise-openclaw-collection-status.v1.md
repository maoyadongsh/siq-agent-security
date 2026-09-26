# 企业 OpenClaw 采集状态 v1

显式授权的配置根必须能够读取 openclaw.json。缺失、权限拒绝或其他读取失败不能作为成功空清单返回。采集器使用既有 Connector 错误信封，固定消息分别为 openclaw_config_missing、openclaw_config_permission_denied、openclaw_config_unavailable；不包含路径、底层错误或配置片段。JSON 解析错误为 openclaw_config_invalid。

一次采集包含多个根时，任一根读取/解析失败，整次返回错误，不提交已经收集的部分候选；历史资产保留，不根据失败推断卸载。空的显式列表可返回空清单；默认角色推导遵循 enterprise-openclaw-default-role/v1，不据空清单断言框架未安装。预算耗尽继续使用既有 truncated 语义，不冒充完整结果。

此变更保留既有协议错误码和数据结构，不自动扩大扫描范围，不执行配置，也不推断实际安装、运行状态或权限。JSON5 支持边界见 enterprise-openclaw-json5/v1；不支持或非法配置仍返回错误，不能假装没有智能体。
