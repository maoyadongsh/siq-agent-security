# R04-B 已保存更新来源一键停用复核

- 日期：2026-09-14
- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- 基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`
- 状态：合同、实现、组件测试与 Web embed 已落盘；未提交、未推送、未合并、未发布
- 结论：**R04-B 组件验收通过；R04/N03 因真实原生更新旅程未完成而保持 partial**

## 交付行为

新增 `local-skill-update-source-disable/v1` 请求合同和
`POST /v1/skill-installations/operations/{install_id}/update-source/disable`。请求严格只有 schema 与 actor，
不携带 URL、locator 或 install binding。后端在单写者槽内重新验证：安装仍为 `installed_unverified`、
没有移除操作、导入工件摘要未变、调度记录结构与签名有效、来源类型和安装绑定一致；Git 还需与导入记录
展示定位一致，ZIP 还需用已保存公开 locator 重算原导入定位摘要。任何不一致均保留原字节。

首次停用只清理 next/last check 和失败状态，保留 locator、display、interval 与 install binding；已经停用的
重复请求不重签、不改时间戳和 actor，逐字节幂等。没有已保存来源返回 409
`skill_update_source_not_configured`，不创建调度文件。旧 `save/v1 enable=false` 保持兼容。

Web 对已保存且启用的 Git/ZIP 统一调用新端点。ZIP 停用不再要求重新粘贴链接；重新启用仍重新绑定原链接。
同时修复“尚未保存的 Git 来源点击启用无动作”。页面把 install/import/actor/服务签名身份作为同步请求
身份，旧页面响应即使在 React effect 清理前返回也不能写入新安装对象。

## 安全与负向覆盖

- 未保存来源：稳定 409，零文件创建。
- 未来 schema、未知字段、坏签名、非法状态、错误 install ID、畸形 JSON：停用返回 changed，原字节与路径清单不变。
- 陈旧 install binding、来源类型或定位变化：拒写。
- 已开始移除：409，停用不可越过移除状态。
- 手动/调度检查取数期间停用：检查的迟到结果因签名变化被拒绝，用户的停用选择保留。
- HTTP 无凭据 401、decision credential 403、错误方法 405、未知/重复/额外字段 400。
- Web 禁止把 URL 放入停用请求；响应若仍为 enabled 会按不兼容响应拒绝。

## 验证结果

| 范围 | 结果 |
| --- | --- |
| Go 针对性 | `go test ./internal/skillinstall ./internal/server` pass |
| Go 并发 | `go test -race ./internal/skillinstall ./internal/server` pass |
| Go 全量 | `go vet ./...`、`go test ./...` pass |
| Web 针对性 | 2 文件 21 项 pass |
| Web 全量 | 24 文件 93 项 pass |
| Web 构建 | 企业版与本地版 pass，embed 已更新 |
| 合同 | Control API 两组合同测试 218 项 pass；Ruff pass；全部 JSON 可解析 |
| 仓库门禁 | 平台验收 40 项、N09 证据 7 项、站点/Actions pin、`git diff --check` pass |

## 诚实边界

本批没有访问公网、没有执行真实上游 V1→V2 更新、没有启动模型，也没有在 Windows/macOS/桌面宿主中
实测。它关闭的是“已保存来源停用无需再次提供 URL”的组件与 Web 行为，不能用于宣称 R04、N03、N08
或 N09 完成。R04 下一步仍是同一候选上的隔离原生 profile 更新、取消、确认、生效、回执和安全移除旅程。
