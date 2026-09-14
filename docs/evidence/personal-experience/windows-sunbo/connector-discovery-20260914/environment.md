# 本批组件验证环境

正式本机执行为 Windows amd64，Go 实际输出为 `go1.27.1 windows/amd64`；uv 为 `0.12.13 (0ebbd9274 2026-09-10 x86_64-pc-windows-msvc)`。本批新增只读OS观测记录 Windows 11 专业工作站版、version 10.0.26200、build 26200、64位/X64、PowerShell 7.6.5；观测时刻为2026-09-14T12:25:49.7196752Z，在checks/schema/native-inventory之后且full-go仍运行。该时序保留，不倒填到更早各命令起点。代码候选为 `d8a66bbdcec988faf2a4e66d3cb7dcfe7e6703bd`，setup/checks/schema/native-inventory/full-go各阶段首尾均clean且未变化。

| 角色 | bytes | SHA-256 |
| --- | ---: | --- |
| Go工具链程序 | 17508352 | d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490 |
| uv程序 | 41556784 | e43cc6ca110540ad845ad6aa1e468e224813eb1da76e145413a262d7073d05e7 |
| inventory.test.exe | 6883840 | 76302ee6a11fc9927fcb25d5e41a67af2197e4af11d7406c11c970ec5f742c5f |
| 正式验证runner | 6072 | eb4cf25b5072e08c5ea1dc064dcdbd13916e6ebd9a1ba3eb3e0d7e844d9a5c90 |

工具及测试二进制摘要已与实际文件重核。setup原summary没有runner摘要；其余四阶段均记录并匹配上表，不为setup补造固定来源。

测试使用独立私有的状态、home、临时与构建目录；公开材料不包含这些目录、用户名、SID或环境值。未为 symlink 前置失败提权或改变系统策略；不根据POSIX mode宣称Windows ACL隔离完成。源码clean只表示工作树状态记录，不证明临时数据已经全部清理；完整Go测试已自然返回exit1，server与skillinstall各发生一次10m包级超时；保留未完成测试，不能称Windows全Go通过。后置记录源码clean、ACL前后相同、限定范围进程0匹配，未杀进程或删除文件。

原生Connector fixture是本次自建Go测试程序的副本，走已有子进程与NDJSON路径。它不等于启动三个真实智能体宿主，也不提供系统级沙箱或平台整体验收结论。四目标制品在Windows生成，除本机组件实际执行外，构建结果只证明可编译。

Ubuntu CI 采用 Ubuntu24.04.5、runner image20260907.300.1；兼容Go1.22.12与严格Go1.26.6分列。对应checkout是合成merge；新增merge-parent原件独立证明其父提交恰为本候选及b303基线；不能把Ubuntu结果重新标注为Windows原生。选定个人路径/PID/SID/凭据模式扫描通过；独立最终复核及主任务公开审阅已完成；最终目录另做提交前秘密扫描。实际失败结果保持。
