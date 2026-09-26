# 0.4.0-rc.2 签名候选包（2026-09-24）

按用户要求更新安装包并同步首页，已从最新合并主线 `7b68c14abeff707777278034f2ccfd19b43ac609` 隔离构建并使用原发行密钥签发 **0.4.0-rc.2**。这是本机准备完成的签名候选，尚未创建 tag、上传 GitHub Release 或替换已安装服务；公开 Latest 仍为 0.3.1。不把候选标为稳定版，不改写旧包与签名。

## 安装资产

本机目录：`.tmp/releases/0.4.0-rc.2-signed/`。

- 完整离线包：`siq-agent-security-0.4.0-rc.2-bundle.zip`，47,359,866 字节。
- SHA-256：`aaf5c5d20fce30022b427b0aeb237c0a41b58b425166ab6a8b949a54c07b881e`。
- 另有签名 Skill ZIP、Linux amd64/arm64、macOS arm64、Windows amd64 四个二进制及两份元数据，共八个资产，见 [SHA256SUMS](SHA256SUMS)。

使用完整离线包，解压到本人拥有的新目录，按包内 `INSTALL.md` 先验签再启动，首次体验使用独立状态目录。候选尚未公开发布，**不要使用 Skill-only 的联网下载模式**；清单中的版本化下载 URL 预留给后续发布，目前未做公开回读。安装步骤和信任范围见[安装说明](../../../signed-release-packaging.md)。

## 源码审阅与构建

本次固定提交已包含 PR #107 的本机开发整合。客户端打包允许清单不包含企业 API / 数据库；企业服务部署沿用其独立记录，不能从客户端包推断企业环境已升级。

最初的 1,829 文件交接清单正确拒绝最新主线，差异仅为以下四个企业 Web 导航文件：

| 文件（相对 `apps/web/src/`） | 差异 |
| --- | --- |
| `api/businessNavigation.ts` | 新增，固定结果解析路径、安全 scheme 与 URL 组成检查 |
| `api/businessNavigation.test.ts` | 新增，9 项 URL / 配置 / 重复证据负向与正向测试 |
| `components/BusinessRunLinks.tsx` | 新增，按资产取数、清理过期异步响应、新窗口无 referrer 导航 |
| `pages/AgentDetailPage.tsx` | 修改，仅为 SIQ 来源资产挂载导航组件 |

已审阅上述增量并通过 9 项测试；React 审查核对了基本类型 effect 依赖与卸载后的响应隔离，无需更改产品代码。基于旧清单仅追加/替换这四项形成新的 1,832 文件清单，未覆盖旧交接清单，也未从待签源码直接重建清单跳过差异。

新清单本机路径：`.tmp/releases/0.4.0-rc.2-reviewed-source-inventory.json`；SHA-256：`151b081b5ee19c91127a4ee46a97ef731fbe0c58d8259bfe743be169775d05f6`。打包器验证固定提交导出内容完全匹配后，重建锁定依赖的本地 UI，确认与提交的内嵌资源一致，再构建四目标。构建输入与工具版本见 [SOURCE-INFO.json](SOURCE-INFO.json)。本机密钥权限与原公钥匹配已核对，私钥未进入命令参数、构建子进程、公开资产或报告。

## 本次验证

- 发行工具 18 项单测通过。
- 官方根验签、Skill 实际内容、四目标二进制 pin、八资产清单/摘要、离线包/Skill ZIP/单文件一致性及安装文本通过，见[验证记录](verification.json)。
- Linux ARM64 最终签名包以独立临时状态完成首次启动、status、pair、控制台访问与停止；未注册后台服务、接管宿主或替换现有客户端。
- Skill 内容篡改、二进制篡改、错误公钥三项全部拒绝，见[负向记录](tamper-rejection.json)。
- 本批所有证据由 [candidate.json](candidate.json) 引用；此前全量源码测试范围见[主线整合记录](../../../development/local-source-integration-20260924.md)，不重复增加测试分母。

## 剩余边界

尚未完成其他三个目标的本包原生安装、跨版本签名升级/回滚、完整宿主旅程、Apple 公证或 Windows Authenticode。原生启动和项目清单签名不替代这些验收。正式公开发布时须固定版本 tag 到上述源码、上传八资产、执行公开回读后再更新下载入口；不覆盖 0.3.1。原 Nemotron、原生 DGX runner、真实业务 IAM 和团队多设备验收继续独立记账。
