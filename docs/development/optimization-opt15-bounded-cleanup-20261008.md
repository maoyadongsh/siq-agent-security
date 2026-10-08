# OPT-15：有界清理的影响结论（2026-10-08）

任务保持 **implementing**，总体仍为 **11/16（68.75%）**。本批不改产品代码，也不再启动日常模型请求。

## 依赖锁定

Go 模块没有第三方 `require`。`apps/agentshield/go.mod` 与 `edge/agent/go.mod` 只有模块路径和 `go 1.22`；各连接器只 `require` 本仓库 `edge/agent`，并用 `replace` 指向相对路径。因此没有 `go.sum`，也不存在可锁定的外部 Go 版本。

已有锁文件：

- `apps/web/package-lock.json`，lockfileVersion 3
- `apps/control-api/uv.lock`，其中 FastAPI 声明 `>=0.115`，锁内有对应精确条目

Hermes 宿主入口 `host_service.py` 只使用 Python 标准库，没有单独的第三方清单。不能把“声明里有范围”说成没有锁，也不能把没有外部 Go 依赖说成锁文件缺失。

## 线性查找

审批 `findHoldResolution` 必须走 `walkVerified`：要确认原 hold 与 resolution 各自唯一，并核对链头序号和哈希。这条线性过程就是验签，不能换成未验签索引。

`uniqueReceiptByID` 只扫描调用方已经验过的切片，空 ID 或两条相同 ID 都失败关闭。在验签之后再做 ID 索引不会去掉验签成本；若在验签前建索引，又会回到按第一条或最后一条取值的问题。因此不改存储结构。

## 生产 assert

三处 `panic` 仍是不变量失败，不是请求可触发的错误返回：

- `runtimeaction/actionid.go`、`runtimeaction/resources.go`：内部规范编码失败
- `modelconfig/config.go`：进程启动时随机源失败

没有新的请求路径能把这些失败变成可恢复错误，所以不改。

## token 哈希

观察者 token、刷新 token 和管理配对码已经按 SHA-256 保存。管理 access token 仍是内存表 `sessions` 的键，刷新记录 `refreshSession.Access` 也保留原 token，否则无法恢复同一次管理会话。只把 map 键改成摘要、同时把原 token 留在刷新记录里，并不能从进程内存中去掉它。这与口令存储不是同一件事，不加盐，也不更换摘要算法。

## 仍未收口

本机是 Linux。Windows WorkBuddy 与 macOS 宿主没有原生机器，不能用交叉编译代替。OPT-11 的正式签发仍要使用已有发布身份，本批不查找、不读取、不生成私钥。OPT-08/10 的资源入口、四臂和最终同候选矩阵也不在本批用新的模型请求补跑。
