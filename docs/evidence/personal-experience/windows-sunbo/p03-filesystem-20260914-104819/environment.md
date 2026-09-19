# 本批环境与证据身份

本批继续使用首批已核对的 Windows 11 专业工作站版 25H2、build 26200.8875、amd64、本地 NTFS 和 PowerShell 7.6.5。完整设备及三个宿主版本盘点见 [首批环境记录](../p00-p01-p03-20260914-094945/environment.md)；本批没有安装或升级宿主。

| 身份 | 实际值 |
| --- | --- |
| SIQ 实现候选 | `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` |
| 执行时 Git HEAD | `973541733ccdb25d4578e56033901e4829ff257c`，各子任务前后相同且 clean |
| 关系 | HEAD 仅含首批报告/证据，受测实现与候选相同；原二进制没有重标源码身份 |
| Windows amd64 二进制 SHA-256 | `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74` |
| 编译来源 | 首批 Go 1.27.1、CGO=0、`vcs.modified=false` 的自建二进制；本批没有改运行代码或重复构建 |
| 测试工具 | PowerShell/.NET 和原生 Win32 API；Python 3.13.7；标准库脚本 |
| 路径 | 新建工作区 ignored `.tmp/win-p03-next` 下各自独立的私有 fixture，不使用 MSIX 虚拟化的 AppData 状态 |
| 父根权限 | NTFS DACL 保护开启，current_user、SYSTEM、Administrators 三条 FullControl，非 reparse |

ACL 子任务仅在自己的新 fixture 上设置合成 Allow/Deny 条目。宽 ACL 分支只有公开 marker、普通初始化元数据和公开固定 seed；随机签名身份只在已核对私有 ACL 的分支生成。宽子文件权限不能靠父目录路径隐蔽来保护，本批没有在宽 ACL 分支生成随机私钥或 token。

Symlink 的无提权创建返回原生错误 1314；没有修改 Developer Mode、系统防护、全局策略或管理员权限。junction 和硬链接单独记录，不替代 symlink 验收。当前没有可用的第二登录身份、第二卷或自有受控 UNC 共享证据，相关范围仍未测试。

原始状态、随机密钥、含个人路径的命令日志及未脱敏签名原件只留本机；只归档经审阅的结果。公开的 admission 展示副本替换了 `source.locator` 路径，原签名字符串保留但不能用公开副本做签名复验，详见 [说明](evidence/links/signature-display-notice.json)。

核心路径问题 [Issue #39](https://github.com/maoyadongsh/siq-agent-security/issues/39) 在本轮开始核对时仍 open、无负责人或评论；[PR #40](https://github.com/maoyadongsh/siq-agent-security/pull/40) 在此前状态快照中为草稿；提交前重新读回确认已由维护者合并，详见下方集成记录。没有擅自合并、发布或修改治理。

Hermes 公共 CLI 尝试使用其安装目录内 Python 3.11.16；Hermes 0.21.2 为首批源码盘点值，当前未取得新的版本命令输出。全新私有 profile 和 loopback 合成 provider 的控制测试未达工具执行；守卫不是 OS 沙箱。该尝试不新增 SIQ 二进制运行结果，未使用真实模型或账号。

本批新增 [Issue #42（宽 DACL）](https://github.com/maoyadongsh/siq-agent-security/issues/42) 和 [Issue #43（路径尾字符别名）](https://github.com/maoyadongsh/siq-agent-security/issues/43)，提交最小复现供共享负责人明确合同；未在本批修改共享安全实现。

提交前重新抓取上游，确认 PR #40 已于 `2026-09-14T02:23:00Z` 由维护者合并，merge SHA 为 `61cf51aba02a521f9f1784af4da5d7e082300206`；审阅者追加的 `bd7276c2c3328d809b1a91a62ff15c0d252a0610` 只修启动器回归测试及审阅记录。新证据分支 `codex/windows-filesystem-evidence-20260914` 基于最新 `main` 的 `df915ca21c25e04b1acbc81956e155f37ffd77e3`。该主线另含 PR #41 的 N09 证据合同/检查工具；相对原候选，SIQ Go 运行目录、Hermes 适配器及本批使用的 `platform_acceptance.py` 没有差异。原测试仍引用 ebc 候选，未重标为新主线实测。
