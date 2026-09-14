# Windows 后续实机验证：文件系统与状态保护

本批补充 Win-P03 的 NTFS 文件边界，并形成两个共享状态修复的最小复现：**WIN-ACL-001：状态与签名身份未拒绝宽读取 DACL；WIN-STATE-PATH-001：尾点/尾空格输入被接受并落到去尾字符的 OS 别名。** 运行代码未改，仍测干净实现候选 `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`；证据不关闭 P03、A10、三宿主旅程或 Windows 总体验收。

环境和版本见 [environment.md](environment.md)，完整文件摘要见 [verification.json](verification.json)。执行 checkout 为 `973541733ccdb25d4578e56033901e4829ff257c`，正式子任务前后 clean，与实现候选只有文档/证据差异。Windows 二进制 SHA-256 始终为 `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74`。本批证据提交及最终 CI 身份在后续 PR 描述单独记录。提交前发现 PR #40 已由维护者合并，遂基于最新主线新建证据分支；[集成记录](integration.json) 保留新旧身份，不改原始测试 SHA。

| 子任务 | 已取得的原生证据 | 未证明的范围 |
| --- | --- | --- |
| [路径与文件占用](evidence/paths/report.md) | 14 个行为场景；尾点/尾空格两例偏移，12 例满足各自限定预期。初版原始 9 pass/5 fail 保留，其中三例测量未确证由新的原生错误32+拒绝+释放恢复补证；共41次初轮CLI和9次补充CLI | 不合并两轮作为完整平台通过率；不证明瞬时零写入、签名发布/rename竞争、任意ADS或其他卷/UNC |
| [junction、硬链接、静态替换](evidence/links/report.md) | 17 次产品 CLI 符合各自预期，包含4次exit1及1次quarantine/exit3；目标和合成外部哨兵的字节、ACL、attributes保持要求，坏marker替换后拒绝 | Symlink 创建错误1314，相关5步未执行；命令开始前替换不等于并发TOCTOU防护；硬链接允许不是全局拒绝别名 |
| [ACL与继承](evidence/acl/report.md) | 6次CLI：私有父根成功；宽继承状态init和公开固定seed加载均被接受；实际DACL给Everyone FILE_READ_DATA；显式创建Deny导致exit1并保留空目录/DACL | 未在宽ACL下生成随机秘密，未模拟第二用户实际读取；没有证明日常密钥泄漏、默认profile不安全或迁移备份ACL已保全 |

这些是 Windows 自建 CLI 和真实 NTFS 的行为观察，不是智能体端到端验收。A09通知、A11活动隐私、A12完整生命周期、可信旧v1→v2迁移和三宿主接入/允许/拒绝/审批/归属仍保留原有缺口；任务书要求的全部旅程没有完成。

## 待共享负责人确认的修复

[WIN-ACL-001 / Issue #42](https://github.com/maoyadongsh/siq-agent-security/issues/42) 建议按 P1 审阅：`0700/0600` 在 Windows 不建立受限 DACL，当前初始化依赖父权限，签名seed加载也未检查宽读取权限。应先明确安全创建、既有目录/密钥检查、Owner/ACE/继承与可审阅修复的合同，再补 Windows 实现；不得递归改任意用户目录权限或把 Chmod 成功当作隔离证明。已观察、推断和未测范围在 ACL 报告中明确分开。

[WIN-STATE-PATH-001 / Issue #43](https://github.com/maoyadongsh/siq-agent-security/issues/43) 应明确状态路径的 Windows 词法及实际目录身份合同：尾字符的短路径输入被接受并落到 `target`，精确扩展路径下请求的 `target.`/`target ` 不存在。应在副作用前拒绝不支持的拼写，或向操作者明确展示规范化目标并遵守对应确认语义，不能静默改写。仅凭这两例不宣称存在目录逃逸或权限绕过。它与 Issue #39 的 Intent/runtime filesystem资源规范化属于不同入口，需共享负责人协调。

## Hermes 公共 CLI 对照尝试与完整矩阵

[Hermes 公共 CLI 报告](evidence/hermes-cli/hermes-public-cli-next-batch.md)记录了一次安装版 Python 公共模块入口的 A 对照：90 秒内没有合成 provider 请求或目标写入，隔离 guard 记录 3 次子进程和 1 次 open 拒绝，具体调用来源 unknown。A 为 blocked，B 的 SIQ 失联场景未执行；已回收直接子进程并关闭本地合成服务。这是测试环境未建立有效对照，不是 Hermes 能力缺失、SIQ 拒绝失败或原生通过。

[18 行完整矩阵](matrix.json)继续保留 144 项检查。两条 Hermes 组件证据从首批按原字节复制到 `evidence/prior-hermes/`，原候选、日期、摘要和 component_fixture 方法不变，仅更新相对证据路径；它们不是本批重新运行的结果。矩阵仍为组件 1 fail/1 pass、其余 142 not_run；结构与摘要校验退出 0，`--require-native` 退出 3，144 项原生缺口未消失。新 CLI 对照未改变这两项既有结论。本矩阵使用独立的 `personal-platform-acceptance/v1` 合同；PR #41 的 `personal-acceptance-baseline/v2` 是 N09 的 9 格 × J1–J11 旅程合同，本批没有将平台检查映射为完整旅程，也不转换历史原始矩阵。

## 证据审阅和保留

初版路径报告的共享冲突原因没有足够现场字段；补充JSON中的CRT原因应当视为假设，以 [独立复核](evidence/paths/independent-review.json) 和路径报告的校准为准。原JSON、脚本与旧候选身份均保留，没有把旧失败改成通过。

链接公开副本对多重编码路径作了脱敏，三份签名 admission 仅修改展示用 `source.locator`，保留原签名字符串；公开副本不用于验签。原始签名对象、原始输出摘要与替换范围分别保留，未重签。除按本子任务记录允许写入的合成状态外，未改日常宿主配置、原有实例或用户目录ACL。

没有为本批文件测试启动服务或计划任务。各文件CLI已等待结束，所有 fixture 与故障现场保留；没有手工删除 Writer 锁、未知文件或原实例。新增报告/合成测试脚本为原创，未新增产品运行依赖，后继证据提交仍引用相同受测实现候选。
