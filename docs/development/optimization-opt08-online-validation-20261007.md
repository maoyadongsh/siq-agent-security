# OPT-08 D2g：宿主发布与在线裁决接线

日期：2026-10-07。状态：在线组件联验通过；OPT-08 仍为 implementing，主任务完成数仍为 9/16。合同为 [native-host-online/v1](../../packages/contracts/native-host-online.v1.md)。

## 本批实现

`serve --native-host` 显式读取本状态目录内的私有连接配置，在 Engine 构造时注入原生查询器；server 在开始监听前仅绑定一次实际身份、安装、签名上下文和调用 Store。旧启动方式保持原行为。新身份的管理创建仍关闭，不能仅凭启动开关把未验收运行栈发布为产品支持。

宿主元数据端点 `/v1/native-host/events` 只接受独立宿主凭据，拒绝普通运行时、管理员/decision 凭据和浏览器来源。固定私有 Unix socket 提供反向核验，逐请求携带新 nonce 并核对完整 subject、制品和有界寿命；不支持代理、重定向或请求指定验证地址。连接配置或 socket 的身份/私密权限变化被发现后，本连接对象停止使用，恢复文件权限也不能自动恢复旧连接。

实际 `/v1/decide` 在既有运行时身份认证后，将原生请求与宿主 Prepare 的摘要做唯一 Bind，再交给现有 Engine 裁决。非 allow（包括 hold）或裁决异常都结束该次在途调用；不会等待一个从未进入的 handler 上报结果。allow 后由宿主 Finish 消耗调用，重复 HTTP 裁决不能恢复执行。

宿主 Python `Verifier` 只允许可信启动器在进程内登记实际 RuntimeGuard；无 HTTP 登记接口。独立线程处理反向核验，避免发布请求等待 Go、Go 又等待同一发布线程的死锁。`Publisher` 把内核通道已经认证的生命周期映射为 Go 事件；已知拒绝以 `accepted=false` 返回，只停止对应任务。真正的运行核验失败仍使 RuntimeGuard 失效。`native_online.Callbacks` 连接元数据通道与既有运行时裁决传输，区分业务 task 和实际 runtime_task_id，不持有宿主发布凭据。

固定镜像构建器新增打包薄通道与在线回调模块，宿主验证器和发布凭据不进入运行时包。新覆盖清单与此前批次分开保存。

## 验证与证据分层

| 层次 | 实际验证 | 明确边界 |
| --- | --- | --- |
| Go 在线 Authority | 真实 HTTP handler、独立凭据、私有 Unix HTTP 回查、签名身份/会话、真实原生 Store 和 Engine；合法/越权、重放、参数替换、deny/hold 清理、失联与配置失效 | 反向运行核验使用显式合成后端，不是实际容器证明 |
| Python 在线映射 | 真实 Unix 凭据通道、HTTP 发布与参数传输、实际 Runtime handler 控制；allow 创建合成文件，deny/hold 不创建 | Go 响应与 RuntimeGuard 是命名夹具，不冒充真实 Authority 或内核隔离 |
| 固定镜像原生函数 | 新覆盖清单下 21 项实际 Hermes 函数探针通过 | 仍是离线合成授权回调，不是业务入口 |
| D2f 内核运行核验 | 前批真实进程、代码、只读挂载、凭据通道 21 项证据继续保留 | 本批没有把两次独立组件测试拼成一条真实 OpenShell 端到端结论 |

Go 全量 45 个测试包通过、10 个包无测试；server 原生在线/身份定向 race 通过，`go vet ./...` 与 Linux amd64/arm64、macOS arm64、Windows amd64 构建通过。四组在线测试含八个反向核验负向子用例；另外一组实际 Go 合同读回样例通过。构建不能代替平台原生验收。

Hermes 适配器本批统一回归 264 项通过。之后调整宿主发布的拒绝反馈，最终受影响的在线映射 5 项再次通过，没有重复其他套件。新增五份在线协议 Schema 与实际 Go 样例经 6 项 Python 合同测试验证；新增/修改 Python 文件 Ruff 通过。合同校验修正了嵌套来源 Schema 的本地引用位置，最终所有生命周期变体均可解析并拒绝额外 Authority 声明。

结构化证据与源码摘要见 [native-host-online.json](evidence/optimization-20261007/native-host-online.json)。本机原始日志为 `var/optimization-20261007/opt08-online-*`，新镜像覆盖目录为 `opt08-native-overlay-06`，不提交原始日志或制品。模型调用为零。

## 尚未完成的真实接入

仍须实现并使用 OpenShell 启动器的真实沙箱/进程归属核验，建立受保护代码、Skill 和通道挂载，再接入智能分析助手日常入口的请求级身份与真实会话。`Callbacks.decide` 由可信 bootstrap 注入既有有界裁决传输；它不是一个可让模型选择 URL 或凭据的工具。

本批证明 deny/hold 不进入 handler 及在途调用正确结束；没有完成 Hermes 自动等待人工审批并安全执行重试的日常交互。两个真实 Skill 的切换/并发/撤权/漂移、实际文件与网络效果、同候选四臂对照及平台验收继续按 OPT-08–15 执行。未推送，也未宣称主线或发行完成。
