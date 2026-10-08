# OPT-01／OPT-02 首批实现与验证（2026-10-07）

基线：`c41347579ebe67c7f732d0e523722e489f831039`。分支：`codex/security-optimization-20261007`。本记录证明本批源码和组件行为，不是新的跨平台原生或正式发行验收。

## OPT-01：回执并发

新增 `TestChainConcurrentSnapshotsAndAppends` 同时运行四个追加者、Head、Read、ReadLimited 和任务快照。将产品文件通过 Go overlay 映射回基线，新测试触发 DATA RACE、序号重复和快照不一致；负向失败来自行为，不是编译问题。

Chain 的统一锁覆盖追加、链头、磁盘读取和 checkpoint 配置；任务快照在同一读锁内核对历史／头／checkpoint。外部 PublishFromChain 的取头与发布同样串行化，避免与本实例追加交错。锁顺序固定 Engine → Chain；扫描回调不重入 Chain。磁盘单写者约束、签名、历史字节和 checkpoint 失败语义保持不变。

验证：

- `go test -race ./internal/receipt -run 'TestChainConcurrent|TestChainAppendFailure|TestHeadHintFailure' -count=3` 通过。
- `go test -race ./internal/receipt ./internal/pending ./internal/server` 三包通过。
- `go vet ./...` 无问题；`go test ./...` 44 个含测试包通过。
- Linux amd64/arm64、Darwin arm64、Windows amd64 构建通过。
- 持久追加微基准：本机 Linux arm64、Go 1.26.5，100 次／轮、3 轮；基线约 6.52–7.30 ms/op，修改后约 6.60–6.85 ms/op。顺序执行、样本小且受文件系统影响，不作性能改善或等价性统计结论。Head 微基准不代表并发状态 API 延迟；不用于对外 SLA。

失效边界：此锁仅约束同一 Chain 对象，不代替跨进程 Writer；同 UID 修改文件、整个目录回滚、跨文件崩溃原子性不在新增保证内。checkpoint 失败可能已有签名行持久化，调用者不得仅因错误盲目重放。

## OPT-02：生产身份隔离

前端只在 DEV 且非 PROD 且显式开发开关开启时注入开发头。Vite 对所有 build 入口和 mode 拒绝 `VITE_DEV_MODE=true`，开发服务器保持显式联调。未修改用户本地环境文件；验证构建通过命令环境传入 false。

- 前端新聚焦 11 项通过：生产／开发身份头行为，以及真实 Vite 配置解析对普通、本地嵌入、自定义 mode 的构建门禁。
- Vite transform 将 client 实现替换为基线后，5 项身份测试中 2 项生产反例失败、3 项通过，证明旧行为确实注入开发头。
- 前端全量 115 个文件、1,029 项通过；`VITE_DEV_MODE=false npm run build` 与 `build:local` 通过。嵌入资源未产生差异；现有大 chunk 提示保留，不作失败或安全问题处理。
- 后端 `test_oidc_jwt_verify.py`、`test_config_security.py` 共 21 项通过；其中新增用例使用受控 RS256 签名与 JWKS，验证开发头不能单独认证、不能改变已验证 JWT 的身份和权限。不是客户真实 IdP 验收。
- 修改的 Python 测试 Ruff 通过。

前端构建防线不代替后端鉴权。本批没有声称原生产后端存在身份绕过。

## 证据与接续

原始命令输出、基线 overlay 和临时测试配置保存在本机 `var/optimization-20261007/`；不作为产品运行依赖或公开原始状态提交。公开回归测试与本记录用于复查。

[实施台账](optimization-tasks-20261007.json)维护剩余状态。OPT-03–OPT-15 与研究候选不因首批通过而关闭。后续改变公共授权或持久化链路时，应按影响重跑这些测试。
