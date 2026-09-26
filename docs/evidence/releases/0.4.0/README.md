# SIQ Agent Security 0.4.0 正式发布记录

用户明确要求将最新候选发布为正式版。固定源码为 `2cd61160849f50794c2dc632771a6e6ed6149eef`，标签为 `siq-agent-security-v0.4.0`。[GitHub Release](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.4.0) 已公开，`prerelease: false`，发布回读确认它是 Latest。此前同源码签发的 `0.4.0-rc.3` 保留为预发布历史，不复用或改名其资产。

## 内容与身份

本版个人客户端加入通过已安装 SIQ Skill 确认浏览器连接、固定 24 小时管理会话、智能体与 Skill 权限事实展示和批量撤权等主线成果。连接请求有效 5 分钟；确认浏览器管理会话不等于批准智能体业务权限。企业 Control API、Edge 和 Connector 代码虽位于同一固定提交，但不在个人客户端安装包的发行允许清单中，不能从本包推断企业服务已部署。

包提供完整离线 ZIP、签名 Skill ZIP、Linux amd64/arm64、macOS arm64、Windows amd64 四个二进制、`SOURCE-INFO.json` 和 `SHA256SUMS`，共八份附件。GitHub 自动生成的源码归档不是签名安装包。签名清单绑定实际 Skill 内容、版本化下载 URL 和四个二进制 pin；`SOURCE-INFO.json` 与校验和是描述性证据，不是额外的源码签名。

## 源码冻结与构建

发行允许清单覆盖 1,994 个文件，清单 SHA-256 为 `3061fb0fee9da4fad64d868f4ccdba0ed7698c9921130a49003ffe9f8b5cac66`。打包器在 npm/Go 构建和签名前逐文件核对固定提交导出内容；首次尝试因提交中的个人端内嵌 UI 与锁定依赖重建结果不同而失败关闭。仅刷新确定性生成的 10 个内嵌资产、通过 Web 与 Agentshield 回归并提交后，才从新的固定提交重新生成清单和签发。

原发行种子只注入签名进程环境；未进入命令参数、日志、构建子进程、公开附件或本证据目录。四目标从同一固定源码重新构建，没有把 `0.4.0-rc.3` 二进制重命名为正式版。

## 实际验证

| 检查 | 本次结果与边界 |
| --- | --- |
| [固定源码 CI](source-ci.json) | 6/6 工作流成功：ci、runtime-security、research、personal-experience、sonarcloud、pages；工作流数量不是测试项数 |
| [最终包验证](verification.json) | 八资产清单/摘要、官方根签名、Skill 实际内容、四目标 pin、离线包/Skill ZIP/单文件一致性、许可与可信安装说明通过 |
| Linux ARM64 原生链路 | 使用最终签名包在全新私密状态完成 start、status、pair、控制台 HTTP 和 stop；未注册系统服务或接管宿主 |
| [篡改拒绝](tamper-rejection.json) | 3/3：修改 Skill、修改二进制、错误发行公钥均拒绝，未暂存不可信程序 |
| [公开回读](publication.json) | 8/8 远端附件与本机已验参考逐字节一致；官方验签、公开校验和下载及 Linux ARM64 签名 URL 下载/暂存通过；`is_latest: true` |

Web 标准测试为 112 文件 / 1012 项通过；Agentshield 全包测试通过；发行工具 35 项测试通过。固定源码的 GitHub CI 另外执行 Control API、Web、Agentshield、Edge/Connector、密钥扫描、研究和运行时安全门禁，结果以 `source-ci.json` 的链接为准，不把不同运行的分母合并。

## 使用与边界

下载安装 [完整离线包](https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.4.0/siq-agent-security-0.4.0-bundle.zip)，同时下载 `SHA256SUMS`，按包内 `INSTALL.md` 先验签再使用新状态目录启动。个人管理端默认只绑定回环地址；远程 Linux 服务应通过 SSH 本地端口转发访问，不要以 `0.0.0.0`、局域网 IP 替换或关闭 Host/Origin 检查。

本次只有 Linux ARM64 完成最终包原生首次启动链路。另外三个目标仅有交叉构建、清单签名与 pin 核对；未完成其原生安装、系统服务、升级/回滚、Apple 公证或 Windows Authenticode 验收。正式版名称不改变这些证据边界，也不证明企业真实组织身份、OpenShell 全行为执行、团队多设备接入或生产部署已经完成。
