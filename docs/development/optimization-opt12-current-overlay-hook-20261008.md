# OPT-12：当前覆盖层的 Linux 受保护加载

日期：2026-10-08。源码提交 `1a07fa8a`。结构化证据：[protected-hook-current-overlay-20261008.json](evidence/optimization-20261007/protected-hook-current-overlay-20261008.json)。OPT-12 仍为 implementing，总体 11/16（68.75%）。

独立 OpenShell 使用当前覆盖层构建镜像 `sha256:12f1c8d96dcba6081bff71358a2134c7abb628926d685e8be7e16fff2eb86f6b`，制品 `8573522ec2dd41fb1c03cc66c6d8325e25d2050de83157c75ba58bbd19239acd`。没有调用模型。18 项运行检查全部为真，钩子和清单的六次写、删、替换均被拒绝且字节不变。真实 Go 权限服务验过 3 条 allow 回执：`skill_view` `rcp-bcbed85fe3a21847863b46105b4d8d4c`，写入 `rcp-9d343d3ab04a7e3bb54fed00d19cce3f` 与 `rcp-a9893995f6af863536a1248ec1b75608`。代码漂移后的写入没有新回执，也没有文件副作用。自有沙箱和网络已清理，日常网关配置与 TLS 未变。

`tools/registry.py` 与 `agent/tool_executor.py` 的摘要和已登记请求镜像 `sha256:534d18c9` 的覆盖层一致。`native_dispatch.py` 摘要 `c3f72d2e` 与当前源码一致。这次镜像不是那张已登记请求镜像，Skill 内容是合成夹具。先前的受保护加载镜像 `sha256:02d70329` 仍保留，不改写。

这不代替当前候选的发行签名身份，也不代替 Windows 或 macOS 原生安装验收。
