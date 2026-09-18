# B00：本轮执行条件冻结

日期：2026-09-15 23:39（Asia/Shanghai）。工作树 `/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`，分支 `kimi/personal-v4-r01-20260914`。

## 1. 基线核对（实际命令与退出码）

| 命令 | 结果 |
| --- | --- |
| `git rev-parse HEAD` | `dafb4cd4a4077feaabad902ad6912ee7d4a2a4cd`（53155b1 之上的文档提交） |
| `git status --short` | 空（0 条未提交） |
| `git merge-base --is-ancestor 53155b10c276fe41e71c47757e58e7e56d5d75d4 HEAD` | exit 0，代码基线在 HEAD 中 |

结论：基线校验通过，留在当前树开发。上一批 r06/r04/r07 成果已固化为 `53155b1`（代码）与 `dafb4cd`（文档）；独立复核报告 `docs/evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md` 的修复即为当前代码候选来源（`5361966882…d942`，/tmp/siq-review-candidate 仍在）。

## 2. 环境事实（详见 environment.json）

- Ubuntu 24.04.4 / aarch64；systemd 255 用户会话可用（未改 linger）。
- go1.26.5 linux/arm64；nvm Node v22.22.1（旅程腿沿用）/ 系统 Node v22.22.2；OpenClaw 2026.5.12。
- **Python 勘误**：当前 PATH 的 `python3` 解析到无关的 ic_master venv（无 Playwright）。带 Playwright 的解释器是 `/home/maoyd/miniconda3/bin/python3`——后续所有旅程/驱动脚本显式使用该路径，不再裸写 `python3`。
- 端口 25173/25177/25191/25201 空闲；无本项目用户单位在运行（前批复核已清理两个 GLM 遗留单位）。
- 信任材料：本机仅有 test-only 签名材料（前批 manifest-v1/v2 均为 test 签名）。**无生产发行信任根材料 → 登记 test_release；正式 release-trust leg 保持 blocked**（解除条件：维护者提供经现有信任根验证的发行清单与两个可追溯版本制品；不使用未授权发布私钥）。

## 3. 本批资源归属

- 私有运行目录 `/tmp/siq-closure-20260915`（0700）归本批所有；敏感临时文件 0600，诊断目录 0700。
- 本批后续创建的 systemd 用户单位、loopback 端口（自 25173 起按需分配）与本目录均在各批次 report 的资源清单登记；**teardown 成功并复验归属后才清理临时目录**。
- 不触碰：`siq-research-engine.service`（预存 failed，非本批）、日常 `~/.config`/`~/.openclaw` 配置、宿主源码、兄弟仓库、系统时钟、全局网络。

## 4. 本轮 checklist（owner=GLM，prerequisite=基线通过）

| 项 | 前置 | 状态 | evidence_ref / 解除条件 |
| --- | --- | --- | --- |
| B00 环境冻结 | 基线通过 | done | 本目录 report.md + environment.json |
| B01 生命周期 runner + 双版本构建 | B00 | in_progress | closure-b01-*；正式发行材料缺失则 release-trust leg=blocked |
| B01 LC01–LC09（test_release 层） | B01 runner | pending | 测试签名可用，可执行 |
| B02 installed_user_service 驱动 | B01 安装实例 | pending | 驱动须验证 state_directory_id/公钥/digest/端口/unit/PID/FragmentPath |
| B02 完整旅程串联（浏览器+宿主，同一安装实例） | B02 驱动 | pending | 新候选后重跑受影响腿 |
| B03 UP05 并发 + UP07 写入口拒绝 | B00 | pending | 独立推进 |
| B04 到期清理 + 任务级导出生命周期 | B00 | pending | 到期腿先落合成记录，自然到期 |
| B05 失联拒绝/副作用零计数/恢复 | B02 实例 | pending | 独立副作用取证 |
| B06 托管来源真网 | 合法网络可达生产来源 | blocked | 198.18/15 消失且获得授权后 |
| B07 B0/B1 对照 + B2/B3 | B00 | pending | 预算先冻结 |
| B08 O05 会话执行 | 真实已配置后端 | blocked | 后端可用后 |
| B09 Windows/macOS | 外部协作者 | external_manual | sunbo/Luke 交付 |
| B10 矩阵/手册/汇总 | 各腿完成 | ongoing | 每批更新 |

## 5. 第一步执行

进入 B01：先建生命周期 runner 与 installed_user_service 最小驱动（读 `client_install.go`/`service_upgrade.go` CLI 实参、`test_systemd_user_service.py` 与 r07 驱动结构），再以独立 archive 构建两个可追溯版本制品。失败结果同样落盘。
