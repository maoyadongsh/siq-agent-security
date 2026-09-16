# B04 双任务 export/trace-export 隔离复核（closure-b04-export-review-3-20260916）

- 日期：2026-09-16；分支 kimi/personal-v4-r01-20260914，HEAD dafb4cd。
- 运行方式：`apps/control-api/.venv/bin/python3 scripts/personal-experience/closure-b04-export-runner.py --binary /tmp/siq-b04-bin/agentshield --out <本目录>`（control-api 声明依赖 cryptography>=50，实际 50.0.0）。
- 结果：passed=true，192/192 项通过，error_type=null（report.json）。
- 覆盖：双任务（export-a/export-b）真实 daemon HTTP 合成捕获；export 与 trace-export 的分页有界、回执非空、scope 匹配、Ed25519 签名验证（信任锚取自所选 daemon 本地 CLI）；私有数据缺席 canary；auth 矩阵（missing 401 / runtime 401 / decision 403，对应 authz.go 语义）；注入 &task_id=foreign 400；跨任务回执 disjoint；撤销后新捕获 409、历史可读；未到期 purge 零写入（状态摘要不变）；仅删除所选记录；过期快照 409 与刷新后导出。
- 过程披露：前两次运行失败并保留 —— export-review-20260916（auth 预期 403 与实际 401 不符，按 authz.go 修正为 401/401/403，收紧断言）；export-review-2-20260916（默认 python3 缺 cryptography，ModuleNotFoundError，改用 control-api venv 解释器，属环境修正）。均为收紧/环境修正，未放宽任何产品断言。
- 权限：目录 0700，文件 0600。
