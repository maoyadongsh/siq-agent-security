# Windows 历史签发交接入口

当前源码与签名发行边界见[说明](skill-source-release-boundary-20260919.md)，安装与新候选打包见[现行指南](signed-release-packaging.md)，无私钥验包见[发行验证工具](../scripts/release/README.md)。正式 0.3.0 的固定身份和实际验证范围见[发行记录](evidence/releases/0.3.0/README.md)。

原 `0.2.1-windows-candidate.1`、多批 `0.0.0-dev` 候选及“旧清单阻塞”描述已属于历史，不再作为当前签发指令。完整候选摘要、准备命令和当时未完成项保存在[原交接正文](https://github.com/maoyadongsh/siq-agent-security/blob/0b2c8135af39071e82effc339cdf88dfd559f9ac/docs/windows-signing-handoff-20260918.md)，相应证据仍在原路径。不要把旧开发归档直接改名为正式版；新发行须对实际源码与二进制重新签名，产品发布也不替代 Windows 宿主完整验收。
