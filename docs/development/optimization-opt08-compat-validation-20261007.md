# OPT-08 C2b：原生权限状态的版本兼容验证

日期：2026-10-07。范围：本地客户端发行声明及升级、回退预检组件；OPT-08 保持 implementing。

## 变更与目的

当前 reader/writer 能力从 4 提升至 5，表示能够读取原生受管会话、精确调用、v2 上下文及 v3 回执。继续沿用既有 manifest v3 和存储格式；没有改写状态 marker、历史文件或旧清单签名。新增 reader5 诊断和测试清单样例，旧 reader3/reader4 样例保留并验签。样例使用公开测试种子和合成制品，不能用于正式发行。

发行预检取候选 reader/writer 较小值检查实际状态。能力低于 5 时，`skill-contexts-v2`、`skill-context-revocations-v2`、`native-skill-sessions`、`native-skill-calls` 任一目录非空即拒绝；包括尚未发布完的临时记录，不能因暂未产生回执而放行旧版本。仅建立了空目录且日志仍兼容时可以通过。

日志检查保留 256 MiB 总读取、10,000 个目录条目和 1 MiB 单行预算。能力 4 可以识别原 pending v1/v2 与 receipt v1/v2；v3、未知版本、原生证明字段（含大小写别名或 null）、重复版本字段和额外 JSON 文档均拒绝。能力低于 4 仍拒绝 v2 本地失败事件。异常路径、符号链接和不合格目录失败关闭。

检查位于原有 `CheckUpgradeForState`、暂存及生命周期事务复验入口；被拒绝的候选不会创建发行暂存目录，后续流程不得据此停止或切换服务。检查只判断兼容性，不替代历史回执验签或授权校验。

## 验证结果

| 场景 | 结果 |
| --- | --- |
| 六类新状态 | 产品生成的签名上下文、撤销、会话、调用、暂存调用及 v3 回执分别阻止旧候选；原字节保持 |
| 读写能力不对称 | reader 4 / writer 5 仍拒绝原生状态；reader 5 / writer 4 同时被既有 manifest 约束拒绝 |
| 当前候选 | reader/writer 5 通过兼容检查；不据此声称业务授权有效 |
| 历史兼容 | 空原生目录与旧 v1/v2 日志可供协议 4 读取；协议 3 继续拒绝 v2 |
| 错误输入 | 未知版本、版本别名/重复、原生证明别名/null、非目录、符号链接、不安全 POSIX 目录权限拒绝 |
| 跨语言签名 | Python 独立验证四份历史/当前清单签名；修改声明能力使签名验证失败 |

- `go vet ./...` 与 `go test ./...` 通过：44 个有测试包、10 个无测试包。
- `go test -race ./internal/clientrelease ./internal/stateformat ./internal/skillmanifest` 通过。
- Python schema 与 native 合同共 336 项通过；1 条既有 Starlette 弃用警告。定向 Ruff 通过。
- linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建通过。跨编译不代替 Windows/macOS 原生验收。
- 原始日志保存在 `var/optimization-20261007/opt08-compat-{vet,go-all,race,contracts,focused}.log`，不提交日志和构建产物。

## 适用边界与下一步

本批保护产品管理的升级、回退流程；不把预检宣称为同 UID 用户直接启动旧程序的 OS 隔离，也不更改旧签名状态来制造不可回退标记。前端、导出等消费者、可信 enrollment 必需路径、固定 Hermes 镜像宿主接入和实际业务效果仍需完成。当前没有启用新的 serve 授权入口，没有推送远端或完成整体验收。
