# Hermes 原生 Windows 决策故障拒绝

## 结果

候选 `e68af01a3753a3d39845b7e1f4c9d01673c5f690` 的原始 Hermes 插件，在真实 Windows Hermes CLI 中完成下列受控故障测试。每场景使用不同私有 profile、Job、模型端口和决策端口；本地固定响应模型不产生付费调用。

| 注入故障 | 实际观测 | 退出与副作用 |
| --- | --- | --- |
| HTTP 401 | 实际 `/v1/decide` 工具参数匹配；响应已发送；真实 tool result 为 fail-closed | CLI/控制器/wrapper均0，无文件、无工具执行子进程 |
| HTTP 200 + 非法 JSON | 实际 `/v1/decide` 工具参数匹配；非法响应已发送；真实 tool result 为 fail-closed | 同上 |
| 超时 | 插件timeout_s=1；实际decide请求延迟1.502秒不发送响应；真实 tool result 为 fail-closed | 同上 |

两项台账 P02-HM-A05-02、P02-HM-A05-03 更新为pass。它们覆盖的是受控故障下真实宿主拒绝，不能替代真实SIQ授权正向、健康服务停服/恢复或Hermes桌面实测。A05-01/04完整要求仍待补齐。台账当前64/303 pass、4 fail、8 blocked、227 not_run；3项用户排除的系统中断测试单列。

## 实际执行链与复现

1. 使用此前原生write_file正向控制的同一安装Python/CLI及身份握手框架；前后核验已固定的103个安装文件。三个场景分别创建新私有目录和配置，保留日常实例。
2. 加载候选原始插件两文件，固定block和1秒决策超时、合成无权限token。精确列举唯一插件目录与三个文件，校验配置和插件摘要。所有账号路径、TEMP、cwd和profile均指向测试根。
3. 模型端点仅返回一个写入本批不存在目标的write_file调用及完成消息。决策故障端点独立于模型端点，仅接受本批真实decide/observe请求，最多4个、正文最多64KiB，逐字核对write_file参数。它不返回allow、不伪造签名回执，不记录认证头值。
4. 分别返回401、HTTP200的`not-json`，或在收到实际decide请求后等1.5秒且不发响应。真实宿主插件与dispatcher运行，没有直接调用插件函数代替宿主。
5. 验证模型端点收到唯一原生工具拒绝结果、目标不存在、workspace空、零工具执行子进程、guard拒绝0。核验实际Python句柄归属及正常退出，专用Job活跃0、无强杀；两个服务监听关闭、线程结束、连接清空、句柄关闭。

超时场景的observe请求在资源清理时提前结束等待1.294秒；decide请求完整等待1.502秒，超过实际1秒限制。两者分别记录，不能把observe清理当作decide超时证明。

## 证据边界

原生CLI、控制器及wrapper退出码均为0，未沿用上一批offline的错误正向探针断言。本批拒绝明确要求零shell探针及零工具执行。上一批原始exit1保持不变；本批是三个不同故障场景，不是重复运行offline刷绿。

JSON保存插件/冻结清单/原始输出SHA256、实际故障请求类别和资源收尾。原始provider请求及guard事件留本机。固定源码未改变，付费调用0。Python audit guard不等于OS沙箱；这组传输故障注入不声称真实SIQ裁决服务签发过授权。
