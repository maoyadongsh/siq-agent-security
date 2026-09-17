# v5 中断接管与验收复核

工作树：`kimi/personal-v4-r01-20260914`；已提交 HEAD `dafb4cd4a4077feaabad902ad6912ee7d4a2a4cd`。本轮保留原有未提交成果，在同一工作树增量修复。未提交、未推送、未合并、未发布。

## 1. 接管事实

GLM 会话中断不等于 B0 进程中断。接管时 B0 `b303c6f` 的冻结测量仍在独立 checkout 中运行。它的 D 场景有三轮，每轮 3 次预热与 60 次样本，每次等待约 30 秒，总计约 94.5 分钟，不是原估计的 35 分钟。

保留该进程和原始样本；B1、构建和全量回归排在 B0 完成之后。复核先检查脚本、原始证据和语法，没有重新启动另一份 B0。

原 closure-b00、b01、b02、b03、两份 b04、b05 共 118 个清单条目的 SHA256 全部匹配。旧报告保持原字节，本报告纠正其中的完成度和证据解释。

## 2. 已落盘修正

| 范围 | 发现的问题 | 当前修正 |
| --- | --- | --- |
| B01 配对 | 无效码代替真实消费码测试重放；未等待过期却标 PASS | 使用已消费码；增加真实 301 秒墙钟等待，显式跳过时 `ok=null/not_exercised` |
| B01 保留重入 | 随机无效凭据被解释为 Grant 撤销不复活 | 创建并撤销真实 Grant，重入核对签名/revision/状态，验证旧会话和再次部署拒绝 |
| Linux 驱动 | 测试使用持久注册、真实用户配置目录中固定名称假单位 | 测试安装/setup 使用 `--runtime`；未知文件夹具留在本批状态目录，不冒充 manager 其他单位保护 |
| B02 HOME | `set-environment HOME` 影响整个用户 manager，立即还原也不能隔离并发启动 | 移除所有全局环境写入；安装前只读验证专用 HOME 前提，缺条件直接阻塞，不绕过 drop-in 归属检查 |
| CLI 诊断 | records 引用返回对象而携带原始 stdout/stderr；可关闭脱敏；种子进入 Go helper argv | 日志仅类别/字节数，records 与返回原文分离；随机排他日志文件；测试种子从 stdin 传入 |
| B03 并发 | 名为多个管理员，实际测试帮助函数全映射到 bootAdmin | 经独立配对签发会话，通过真实 loopback HTTP 和同步起跑进行并发请求 |
| B03 签名 | 修改 analysis 命中外层摘要，且接受任意非 2xx | 修改有效 JSON 中的签名 hex，准确要求 409 `skill_import_changed`，并核对整个目录零变化 |
| B04 隔离 | export 成功、未知 ID 404 不足以证明跨任务隔离；缺 trace-export | 双真实运行时绑定任务的 HTTP 导出；逐项回执/来源、撤销/删除/清理、旧快照、管理权限和 canary 检查 |
| B04 组件 | 清理仅对比授权文件名，不验证字节 | 对比授权文件原字节；另补三任务签名 export/trace-export 在撤销、删除和到期清理前后不混入数据 |
| B07 对照 | D 时长与继承注释不准确；C/E 不能按同工作量比较 | 汇总器验证哈希、全部原始样本、轮次、预算和时间顺序；C 工作量变化/E 无旧实现分别报告 |
| B10 用户材料 | 缺覆盖本轮目标的个人操作手册 | 新增[个人操作手册](personal-client-operation-guide-20260916.md)，状态统一回写任务书和台账 |

这些修改主要修复验收脚本的误判、隔离和信息披露问题。生产代码是否需要改变以新增负向回归和真实验证结果为准，不为满足报告而放宽产品合同。

## 3. 本轮验证

已完成：Go vet / 全量 test / server、rawcontent、skillinstall race 全部退出 0；Python 合同全量退出 0；四目标 CGO=0 构建成功。最终脚本负向回归 33/33，Ruff 与 git diff --check 通过。详见 [validation](evidence/personal-experience/closure-review-validation-20260916/checks.json)。

- B01 实测 35/35，包含真实 301 秒自然过期与已撤 Grant 保留重入；崩溃腿修正为产品实际支持的显式服务重启，r2 8/8。正式发行信任腿仍缺失。
- B03 双 CLI 44/44；独立管理员 HTTP 并发是另行 Go 测试，不能将两种证据混成一个实机计数。
- B04 双任务 HTTP 导出独立复核各 192/192；B05 最终 r3 16/16。
- 修复共享 OpenClaw Harness 忽略 --binary 并自行编译 HEAD 的问题。现在复制指定候选并检查摘要；B05 r3 的候选为 53619668…，不再用新编译二进制冒充指定候选。
- B02 安全前提检查结果 blocked，产品动作 0；旧报告的共享 manager HOME 设置后还原并非实例隔离，不予验收。
- B07 原 B1 双跑均失去正式资格；随后声称干净的 02:20:51–02:22:01 UTC 重跑又落在本轮 Go race 区间内，已加 INVALID，保留原数据。
- 在所有本轮测试结束后，以独立 detached checkout dafb4cd 单独补跑 [B1](evidence/personal-experience/openshell-o04-perf-20260916-030440/)，复用原有效 B0；[最终对照](evidence/personal-experience/closure-b07-final-review-20260916/report.md)绝对预算全过。等工作量相对门槛仅 diagnose_unconfigured 未通过：p95 0.019→0.022 ms，+15.79%；其余 A/B/D 均通过。保留该失败，不放宽 10% 门槛。C 工作量变化、E 无 B0，不纳入等工作量通过。
- fsync 归因补测仅说明追加持久化在观测时间中占比较高，不能证明原回退由噪声造成，也不能取代冻结门槛。
- [最终矩阵](evidence/personal-experience/closure-b10-final-review-20260916/matrix.json)改用 B04 r2/B05 r3，同候选 9 格、99 行、0 个 complete_acceptance，v2 校验通过。

## 4. 未关闭边界

- B01 正式发行签名材料未提供，test_release 不等价正式发布验收。
- B02 当前产品签名 unit 不提供本批可用的实例 HOME 配置，未知 drop-in 会被拒绝；共享 manager 的环境不可修改。需要受支持的实例范围配置或专用用户 manager 后重跑。
- B03 两版 CLI 负例使用合成未来/损坏状态，不能称真实未来版本迁移成功；各 HTTP 写入口覆盖仍按清单分层。
- B04 新 HTTP 腿不是原生宿主采集；原真实墙钟到期腿另列，组件时钟注入也另列。
- B06 09:30 前后的只读重查：GitHub/codeload 仍解析至 198.18/15。未修改 DNS、HTTPS 或 SSRF。
- OpenShell PATH doctor 返回 `configured_unreachable`、`probe_ok=false`。历史 17671/17672 有监听，但未证明本批可用、归属确认的独立后端，B2/B3/O05 不能据此关闭。
- Windows/macOS、Linux WorkBuddy、桌面通知视觉和原 N09 九组合验收继续保留；sunbo/Luke 职责不变。T01–T06 仍受 N09 前置门槛约束。

## 5. 证据与下一步

本轮新证据放在 `docs/evidence/personal-experience/closure-*-review-20260916/`，各批保存准确候选、脚本/报告摘要和实际退出状态。失败证据不删除，修正后的运行使用新目录。

B07 原始运行结果分别保存在新的 `closure-b07-review-20260916/b0`、`b1`，比较结果单独保存；汇总不覆盖任何输入文件。未执行的项目继续保持 partial/blocked，不缩减任务书原分母。

## 6. 当前交付与资源

本轮改动保留在原分支，未提交、推送、合并或发布。自建生命周期 unit 已复查 MainPID=0、LoadState=not-found、inactive。性能 runner 已结束；独立性能 checkout 与 `/tmp/siq-takeover-review-20260916` 调试材料保留在本机供追溯，不上传，未宣称所有临时文件均删除。外部服务未停止。

下一步优先解决 B02 支持的实例 HOME/专用 manager 接入，再做正式发行信任腿。B07 保留微秒级诊断相对预算缺口和 B2/B3 真实后端缺口；不反复抽样挑选通过结果。跨平台任务及 N09 门槛保持不变。


## 7. B02 后续实现（2026-09-16，覆盖前述当前阻塞状态）

新增 `config.json.linux_service_home`，经 canonical 路径校验后写入原有签名 unit；无字段时原字节兼容，HOME 变更不能替换旧签名归属。无全局 manager 环境写入，不使用未知 drop-in。该功能是配置隔离，不是沙箱。

真实 Linux/arm64 + OpenClaw 的 test_release 安装链完成 15/15、浏览器旅程 26/26、同候选直接进程 25/25；安装、重启、停止、卸载、保留状态重入、回执历史与实际进程 HOME 读回通过。最终无本批用户 unit，成功运行的临时目录由 runner 清理。

验收 runner 也修复了初始化 HOME 时序、缺 Playwright 预检、失败时 driver 尚未返回造成漏清理，以及 R07 使用 status 而非 ok 的汇总问题。前两次失败保留 NOT-ACCEPTED；第三次原报告误写 failed 明细与旧 HOME 说明已在独立复核文件纠正，不改写原样本。

Go vet/test、cmd/state race、四目标构建及 36 项脚本回归通过。详见 [B02 实测](evidence/personal-experience/closure-b02-scoped-home-20260916-r3/report.md) 与[最终复核](evidence/personal-experience/closure-b02-home-validation-20260916/verification.json)。构建采用 dafb4cd 加显式记录的本地生产 Go 源码摘要，测试发行根仅在独立构建副本修改；不是正式签名发行。原 B10 矩阵候选未自动升级为新候选，N09/T01–T06 门槛不变。

下一步：准备正式受信制品的 B01/B02 验收；取得独立真实 OpenShell 后端后推进 B2/B3/O05。B07 诊断相对预算缺口仍保留。所有本批修改仅落盘，未提交/推送/合并/发布。
