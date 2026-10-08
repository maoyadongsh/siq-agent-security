# OPT-08 日常业务内容版本（2026-10-08）

当前安全二进制 `aa25999e50226f9758976a149350086294b21ab737a42aa910bdb5345d07aea5`（代码提交 `8c473439`，文档提交 `8f57b92f`）配业务 `8851724`，在 DGX 日常模型上完成一次内容版本升级拒绝。

已安装的用户监管单元和 `qwen38-supervisor.env` 仍是 `SIQ_PROJECT_ROOT/var` 合同，当前业务代码要求 `SIQ_RUNTIME_ROOT`。产品 `install()` 发现字节不同时拒绝覆盖。v873、v875、v877 因此在模型调用前停在 `supervisor_service_install_required`。v879 仅在本轮执行期间把这两份文件改成当前合同，结束后按原字节写回并 `daemon-reload`。单元摘要 `02fb70569d9b198ea4aa7958b537483dc1022cd1ad0a71ac994c02e9cedd28df`、环境摘要 `9a3440c207a4555d32c7adbf6b0f82fb78ac27586cc22ab0580e25105dd2bba8` 前后一致。模型单元保持 active，自有桥接停止后保持 inactive。

v879 `content_upgrade` 33 项检查通过。安装前 `SKILL.md` 为 `014ac3788981848b9917115b8701ad7483bd9067a22c1939f5588d2cce0c7b12`，提交后为 `a38f8af2dfefc099c18b9876d2f8e565be77c72f5ccaf7ad1cdbd95a209759db`。旧 Grant `grt-si-5071d59aa888a3f0eae30f44ee5542242d409ac761dac4e6baf733373e397a58` 状态为 revoked，新安装 `sin-ea1e0c217b0cbf6ecbed9c4952f38d36adc7107ed40ce8d7c6371f60744d6595` 对应 Grant `grt-si-958dfcacce7524582e2bd6bb58d0dd0e3576c54503b758216eaefefac4c82595`。暂停中的旧任务恢复后实际尝试 `write_file`，没有写入回执，目标文件不存在。链上只有更新前的 `skill_view` allow `rcp-b30be176f22cf2eb3735f2188f339618` 和 `read_file` allow `rcp-11223f4014a18b93076ba3786ca0bda6`。Agent 基线 `grt-id-5c9bfc0e41508181b51d1c9888c6bc9f467e9b46b19e8e9c1053e38804711809` 仍为 deployed。运行时制品仍是 `070e94236ba603b6e7cff70f217e3a43e15f20dd7213cb03cabade3c2cf553b2`。

v880 新任务对照没有通过。SSE 以 `consecutive_tool_errors` 结束，工具结果写明 `native_dispatch_unavailable`。Authority 只为该任务记下一条无 Skill 上下文的 `skill_view` allow `rcp-90c7b28db48fee28cf1a15241e6be3f3`，没有读取回执，也没有为 V2 安装签发新的 Skill 上下文。现场唯一上下文 `sec-d62b986c6dd6e8c04846ca00338145f3` 仍指向旧安装。随后核验脚本在 `writer_control` 尚未写入故障记录时读取 `context_id`，额外抛出 `AttributeError`；业务失败本身已经发生。没有新文件。

这不是最终矩阵。新内容上的独立读写尚未执行，资源/工具入口、四臂、平台和签名交付仍未收口。OPT-08/10 保持 implementing，总体仍为 11/16（68.75%）。
