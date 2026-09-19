# Win-P03：NTFS 链接与静态目标替换

本轮 17 次原生产品 CLI 调用符合各自测试预期。测试覆盖 junction、硬链接和命令启动前的文件替换；symlink 创建返回 Win32 错误 1314，相关 5 步未执行。**这批证据只补充文件边界，不关闭 Win-P03，也不证明任何宿主端到端拦截。**

当前干净 HEAD 为 `973541733ccdb25d4578e56033901e4829ff257c`。受测 Windows 二进制仍来自候选 `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`，SHA-256 为 `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74`；两个提交之间仅有文档/证据变化，未重新构建或重跑上一批门禁。每次调用前后均核对 HEAD、干净工作区、实现文件差异和实际二进制摘要。

## 实测结果

| 场景 | 命令数 | 实际结果 |
| --- | ---: | --- |
| 普通中文/空格状态目录 | 3 | init、state-status、重复 init 均退出 0；身份保持一致，重复初始化保持完整文件字节、ACL、attributes 和文件身份 |
| 状态根、祖先及 keys 核心目录 junction | 6 | 三条 state-status 均退出 0 且 compatible=false/status=corrupt；对应 init 或 pubkey 均退出 1。完整测试树及外部合成目标不变 |
| state-format.json 硬链接 | 2 | status 和重复 init 均退出 0；原生句柄读回相同文件 ID、link count≥2。硬链接按普通文件处理，额外目录项及内容不变 |
| 预先替换硬链接 marker 的目录项 | 2 | File.Replace 完成后 marker 的文件 ID 改变，原硬链接别名完整字节保留；随后 status 为 corrupt，init 退出 1，产品没有修复或覆盖坏 marker |
| 独立扫描状态初始化 | 1 | init 退出 0，只在自己的扫描状态内创建文件 |
| 普通 Skill 与硬链接普通文件 | 2 | admit 均退出 0/verdict=admit；硬链接内容摘要与外部合成别名吻合；输入和哨兵不变 |
| Skill 内指向根外合成目录的 junction | 1 | admit 退出 3/verdict=quarantine，含 adm-symlink-escape；symlink_escape=true，外部哨兵没有进入 file_manifest；输入与哨兵不变 |

五个非零退出均为预期拒绝，其中四次退出 1，一次 quarantine 退出 3；没有把诊断命令退出 0 当作兼容。扫描的准入、证据、签名密钥只写入本轮独立扫描状态，未执行 Skill 内容、真实 Agent 或模型。

symlink 使用原生 CreateSymbolicLinkW，flags=2（允许无提权创建）仍返回 1314。没有申请管理员权限、修改 Developer Mode 或用户配置。根内文件 symlink 正向、根外 symlink quarantine，以及 symlink marker 的准备/诊断/初始化步骤均保持未执行；没有用 junction 冒充 symlink 通过。

## 方法与保留现场

所有目标、链接、替换源/备份和“根外哨兵”都位于新建 `<LINK_TEST_ROOT>` 内。所谓根外仅指被测 Skill 或状态根之外的合成同级目录，不涉及真实用户文件。父目录 DACL 保护开启，仅当前用户、SYSTEM、Administrators 三条 FullControl；子根继承这三条规则。当前进程没有管理员提权。

子进程通过 `ProcessStartInfo.ArgumentList` 接收独立参数，`UseShellExecute=false`、`CreateNoWindow=true`；状态目录仅在子进程环境中指定。各 JSON 保留脱敏后的真实 argv 数组、退出码、stdout/stderr、耗时及前后清单，没有通过 PowerShell 拼接命令来推断 argv。

清单不跟随 reparse 目录。使用带 `OPEN_REPARSE_POINT|BACKUP_SEMANTICS` 的原生句柄读取文件 ID、link count、attributes，以及 owner/group/DACL；普通文件完整字节在私有内存中比较，公开证据仅保留 SHA-256。拒绝命令比较整个合成树；允许初始化和准入时，只允许自己指定的状态子目录变化。未纳入 last-access/目录修改时间或 SACL，不能把本测试扩展为这些元数据的保持保证。

目标替换在命令启动前以原生 File.Replace 完成，原对象通过硬链接别名和替换备份保留。此测试证明下一次入口对现有坏对象的静态拒绝，不证明抵抗同 UID 并发替换、跨文件系统、任意 reparse tag 或崩溃恢复。硬链接通过也不表示能够拒绝同一文件在其他目录中的所有别名。

没有清理测试树、删除实例或锁，也没有注册计划任务或启动服务。全部现场保留在私有根。`private-raw` 内含未脱敏路径、原始字节与生成密钥，只能本机保留，**不得归档**；只归档本 `archive` 目录；原 `evidence` 草稿也留在私有根，部分草稿包含多重编码的本机路径。临时 harness 的摘要见 `harness-provenance.json`，harness 本身含本机路径，仅本机保留。

入口契约依据：开发规格的状态预检、初始化、扫描打开保证，以及 ADR-013 的 Windows 残余 TOCTOU 边界。`statefs` 是兼容性检查包装，不应把它解释为对所有普通文件硬链接的全局拒绝策略。

证据索引：`final-observation.json` 汇总 17 次调用与最后清单；每条同名 JSON 保存前后细节；`hardlink-target-replacement-setup.json` 保存替换本身的观测；`symlink-capability.json` 保存真实能力失败。

归档阶段对嵌套 JSON 的多重反斜杠路径进行补充脱敏；私有原始字节和初始 harness 摘要保留，未重跑或改写测试结果。归档使用的 harness 与包装脚本摘要另见 packaging-provenance.json。

## 公开签名对象的展示边界

三份 admit 输出包含已签名对象。公开副本仅把 source.locator 的本机根路径替换为占位符，保留原 signature 字符串；其余解析后的对象字段逐份核对相同。这些脱敏对象只用于展示与行为证据，不能用于签名复验。私有原始签名对象完全保留，没有重签。每份原始 stdout 的 UTF-8 SHA-256、私有封装日志摘要、公开 stdout 摘要及精确替换范围见 signature-display-notice.json。需要签名复验时应使用本机保留的原件。
