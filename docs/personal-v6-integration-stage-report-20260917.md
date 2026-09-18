# 个人版 v6 集成阶段报告（2026-09-17）

## 1. F00–F10 状态与原任务映射

**整本任务书尚未完成。** 进度以[动态台账](personal-v6-integration-progress-20260917.md)为准，原 D/E/B/N/R/O 分母保持；2026-09-17 [产品范围决策](personal-platform-scope-decision-20260917.md)只把 Linux/WorkBuddy 排除，不把它计为通过。

| 项 | 状态 | 实际边界 |
| --- | --- | --- |
| F00 集成保护 | 阶段完成 | 从 `9b8c09af…` 基点保护并采纳 GLM 源、合同与证据，未改原工作树 |
| F01 加载与授权 | 本机部分完成 | 真实 0.0.83 网关上 UUID 签入批准、预留前双读回及旧批准拒绝已有组件/服务证据；E11 修复后候选 `0b16e5e0…` 的 D05 同候选复测 229 pass / 0 fail；CLI 按名称执行仍无网关原子性 |
| F02 停止/恢复 | 部分完成 | 签名持久记录、拒绝重放及本地停止可验；v0.0.83 未证远端单任务停止，保持 uncertain |
| F03 界面 | 本机 E12 同候选通过、总体 partial | `0b16e5e0…` 的 D05 E12 真实浏览器 × daemon × 沙箱 12 个子检查通过；跨宿主和其他 OS 不继承 |
| F04 D05/E01–E13 | 部分完成 | 同候选扩展 D05 原记录 344 步 337 pass / 6 partial / 1 blocked / 0 fail；[复核](evidence/personal-experience/v6-f04-closure-review-20260917/report.md)后的采纳汇总 10 pass / 3 partial（E06/E08/E11）。E04 仅决策平面；E11k 真实写盘故障已采纳 |
| F05 性能 | 最新候选本机绝对预算通过、总体 partial | `0b16e5e0…` 测前冻结协议、3 轮 150 有效样本、0 无效、S1–S4 绝对预算内；相对基点未测或不可比，跨平台与发行级未验 |
| F06 Linux 隐私/失联 | OpenClaw 与 Hermes 各自原生到期腿通过，总体 partial | 旧候选 OpenClaw、Hermes、导出、D-Bus 有逐腿证据；两次独立墙钟密文到期核验各 19/19。`ac447ac9…` 的 OpenClaw 撤销对照 19/19、90 秒自然到期后原生新调用 20/20；`0b16e5e0…` 的 Hermes SEC 原生回归 11/11、60 秒自然到期后新调用 17/17。同候选 OpenClaw R07 现有脚本旅程 25/25、嵌套更新 30/30 已复核；安装摘要关系断言、R06 联合旅程/原生 hold、GUI 及其他 OS 仍待验 |
| F07 企业服务 | 开发服务级分腿通过，总体 partial | 隔离 uvicorn HTTP 到真实网关 33/33；不代表生产 OIDC/PostgreSQL |
| F08 托管源/平台范围 | 托管源 blocked；本机 Linux/WorkBuddy 与全平台 CodeBuddy 新接入门禁已实现 | GitHub 源仍解析到 198.18/15；Linux/WorkBuddy 退出本机范围；CodeBuddy 退出全平台范围；Windows/macOS WorkBuddy 继续实机线 |
| F09 平台协作 | 外部实机待验 | Luke macOS 三宿主阶段性推送，WorkBuddy 阶段性完成；sunbo Windows 部分分支已推送、仍开发；交叉编译不算原生通过 |
| F10 交付 | 阶段进行中 | 新候选同候选 D05/E12/F05 已补证；本地未提交成果可审，PR、合并、正式签名及发行未执行 |

## 2. 实际验证与证据等级

- `ceddc59c…` 候选在真实 OpenShell 0.0.83 网关、真实沙箱、真实 SIQ daemon 的 [D05 矩阵](evidence/personal-experience/v6-f01-identity-live-r2-20260917/report.md)：229 pass、0 fail、E 项 9 pass / 4 partial；E12 包含真实浏览器。先前一次因隔离网关元数据缺失失败，原样保留；驱动 K02 `probe.ok` 的早拒绝已补负例。
- [`ceddc59c…` 独立性能](evidence/personal-experience/v6-f05-identity-20260917/report.md)：测前冻结协议、三轮、150 个有效样本、0 无效、S1–S4 绝对预算全过。首次排他预检因竞争进程在零样本处停止并留档；相对基线未验。
- [`ac447ac9…` Linux 范围候选](evidence/personal-experience/v6-linux-scope-20260917/report.md)：Go 全量/vet/race、Python 两份诊断合同样例、Web 115 测试与嵌入构建、四目标交叉编译和隔离 CLI 五项新接入拒绝及真实嵌入浏览器两页门禁通过；尚未重跑 D05、完整浏览器旅程与性能。
- 旧候选 [F06 Linux 分腿](evidence/personal-experience/v6-f06-20260917-175500/report.md)：OpenClaw 失联 16/16、原生采集及撤权 19/19、Hermes SEC 11/11 和失联 9/9、双任务导出 192/192、D-Bus 通知 6/6；[两次独立真实墙钟到期核验](evidence/personal-experience/v6-f06-expiry-20260917-174400/report.md)各 19/19。各腿不等同完整原生用户旅程。
- [OpenClaw 原文自然到期原生腿](evidence/personal-experience/v6-f06-raw-native-expiry-20260917/report.md)：同一 `ac447ac9…` 二进制的撤销对照 19/19、90 秒墙钟到期后新调用 20/20；许可 410，到期后允许读取仍有签名回执但无新原文。错误宿主与脚本失败试跑保留，不记通过。
- [E11 修复后 Hermes 原生 SEC 腿](evidence/personal-experience/v6-f06-hermes-post-e11-20260917/report.md)：新构建 `0b16e5e0…`、Hermes v0.21.0 公共 CLI 与隔离 HOME，11/11；这次 SEC 回归本身不含到期；同候选 D05/E12/性能见下方独立证据。
- [同一 `0b16e5e0…` 候选的 Hermes 原文自然到期腿](evidence/personal-experience/v6-f06-hermes-native-expiry-20260917/report.md)：最终 17/17，Grant 到期、permit 410、同一原生任务允许新调用且原文记录不增；默认 SEC 对照 11/11。前两次因 Hermes 对未变文件返回 `unchanged` 而失败，私有日志保留，脚本改用不同合成文件后重跑；最终证据有脚本摘要及时间顺序。
- [E11 修复后同候选 D05](evidence/personal-experience/v6-f04-post-e11-d05-20260917/report.md)：真实网关、独占沙箱、daemon 和 E12 浏览器；238 步中 229 pass / 8 partial / 1 blocked / 0 fail，E 项 9 pass / 4 partial。真实结果/审计写盘故障仍未注入。
- [同候选 F05 独立性能](evidence/personal-experience/v6-f05-post-e11-perf-r2-20260917/report.md)：测前 R4 协议、3 轮 150 样本、S1–S4 绝对预算全部通过；第一次缺协议的零样本失败原样保留。
- [F07 开发服务](evidence/personal-experience/v6-f07-20260917-174700/report.md) 33/33 为隔离开发身份/SQLite 的 HTTP 到网关验证。
- 新候选 Go `go vet ./...`、`go test ./...`、受影响四包分两组 `-race` 均 exit 0；Python API 全量 pytest/Ruff、脚本负例 14 项、Web 26 文件 115 项测试与 `build`/`build:local` 均 exit 0；四目标 CGO=0 构建成功，Linux/arm64 复编摘要等于实测二进制。N09 校验器 8 项负例/33 子项通过，旧矩阵完整性校验 exit 0；校验不等于发行验收。命令及交叉构建摘要见 [F01 checks](evidence/personal-experience/v6-f01-identity-live-r2-20260917/checks.json)。

- [同候选 R07 独立复核](evidence/personal-experience/v6-f06-r07-review-20260917/report.md)：原机器记录 25 个旅程检查与嵌套 30 个更新检查通过，失败轮保留；本次离线复核不等于重跑，不能确认首次超时是瞬时波动，亦不能由非空摘要推定密码学关联已验。

## 3. 缺口、原因和解除条件

F01 的 UUID 读回与 `exec -n` 仍非网关原子操作；需上游稳定执行句柄或等价原子选择能力。F02/E08 的远端单任务停止未在 v0.0.83 得到可核实读回，不能用本地进程退出替代。F04 已采纳过期 SEC/必需 Authority 决策平面、加载窗口及 E11k 真实持久故障；E06 不支持等待选项分支、E08 远端停止与 E11i 超时归因仍为 partial。F06 的 `ac447ac9…` 候选已补 Linux/OpenClaw 原文 Grant 自然到期后的原生新调用；`0b16e5e0…` 候选已补 Hermes SEC 与原文自然到期原生新调用。两宿主证据各自有效，同候选 OpenClaw R07 现有脚本旅程已通过并[复核](evidence/personal-experience/v6-f06-r07-review-20260917/report.md)，首次超时根因仍未明；摘要关联断言已由 [补强实测](evidence/personal-experience/v6-f06-r07-attribution-20260917/report.md) 的逐字段关系与错配负例补齐；R06 联合旅程、原生 hold、桌面视觉及其他 OS 独立验收仍保留。定向清理和存活腿已在旧候选 direct-process daemon 上完成。F07 生产身份/数据库、F08 可信公共 DNS/直连托管源、F09 Windows/macOS 实机、正式签名与发行均需各自真实条件。Linux/WorkBuddy 是**产品范围排除**，CodeBuddy 新适配全平台取消；二者均不属于当前目标。若未来恢复须新产品决定与完整原生证据。

E11 已增加结果文件与审计写盘失败的组件级故障注入：任务启动后的非零退出或本地超时在证据不完整时返回 503，保留执行不确定性和预留，不返回原始输出；Go 全量、vet 和定向 race 通过。[独立补证](evidence/personal-experience/v6-f04-e11-durability-20260917/report.md)。这项源码变更晚于 `ac447ac9…` 构建，不能移用该二进制的原生到期或平台门禁证据当作新源码的 D05 通过；随后 E11k 三种真实写盘故障已补证并由[独立复核](evidence/personal-experience/v6-f04-closure-review-20260917/report.md)采纳；E11i 的非零 CLI 退出归因仍保持 partial。

## 4. 源码、候选与证据绑定

集成基点 `9b8c09af742cb9df94c6d02e6f2db6ecccd68951`，当前分支 `codex/personal-v6-integration-20260917`，仍为未提交脏树。F04/F06/F07 旧候选二进制 `c8048691276590a064b5314837e35c80a2e8fba48471f1bf12c434f6b9ae9853`；F01 身份绑定与 F05 性能候选 `ceddc59c929da6ae449fdcb06f5e4f5915bf2e3ca73dad73457be421fbb194e7`；Linux 平台范围及 OpenClaw 原文到期候选 `ac447ac92e65997952dc5a19ead7a83a8512924948a43f986d7f0d66aa0366ff`；E11 修复后 Hermes 原生 SEC、D05 与 F05 同候选 `0b16e5e09e6d807b5be732e390c373e6a4354d096b272eba827bddb84a6c8177`。这些候选证明不能交叉移用。各自 candidate 与源绑定见对应证据目录；公开报告各有独立 SHA256SUMS，原始私有材料只在忽略的 `*-private/` 目录中。

## 5. 影响、兼容与 Git

安全核心的新批准参数包含沙箱 UUID；不含该字段的旧原型批准会拒绝，需重新预览并批准。历史 `policy_apply` 与真实命令执行保持不同接口和副作用账本。N09 新矩阵可把 Linux/WorkBuddy 整格标为 `out_of_scope`，旧矩阵不重写；旧离线 QA v1 十八行仍可校验历史材料。Linux UI/API/CLI 已阻止 WorkBuddy 新接入，全平台关闭 CodeBuddy 新接入与 Grant 激活，保留历史查看/拒绝/撤销/卸载；底层通用 connector 不据此宣称 Linux 原生支持。所有代码、文档、证据仅在本地工作树，**未 commit、push、merge、签名或发布**。回退须按审查后的补丁撤销本集成树变更，不 reset 其他工作树或重写历史证据。

## 6. 资源与收尾

本批 F01/F05 及 post-E11 D05/F05 独占沙箱已核对 UUID、按确切名称删除，并只读复查不存在；共享网关未重启、未改全局配置。F06 两份独立隔离到期验证均已在真实墙钟期限后完成，各自 daemon 已由 runner 停止，原始私有证据留在忽略目录并限制为目录 0700、文件 0600；两份验证端口已确认无监听。F01 与 post-E11 预检的隔离 mTLS 临时副本均已清理，候选二进制保留在独立临时目录供摘要复核。私有输出、配对信息不纳入公开材料；只清理本批可确认归属的资源。
