# macOS Luke：桌面钩子所有权修复与范围裁决

**结论：未完成 Mac-P00–P05 整体 macOS 验收。** 本批以干净提交 `450fe1836d8a3bffefbd2ce9b6f02bbbfe730c64` 重建 arm64 候选并验证桌面配置恢复修复。OpenClaw、Hermes 原生 CLI 回归通过；WorkBuddy 本候选仅完成隔离配置安装/卸载，桌面输入的“发送”控件不可用，未产生新的宿主工具调用，因此不继承旧候选的桌面通过项。用户于 2026-09-16 明确放弃 Intel/amd64 实机，本轮只以 Apple Silicon/macOS arm64 为架构目标；不把 Intel 留作完成阻塞，也不冒称 Intel 已支持。

| 身份 | 值 |
| --- | --- |
| 候选/分支 | `450fe1836d8a3bffefbd2ce9b6f02bbbfe730c64` / `codex/macos-luke-p06-20260916-153008`，构建时干净 |
| 制品 | Mach-O arm64、CGO=0、`-trimpath`、隔离 go1.27.1；SHA256 `f067f96b05c3472b8ebe2d43ac9c19ce79c5063af19ec1dc66999a6da1bd3e23` |
| 设备/宿主 | macOS 26.6.2、Apple M4；OpenClaw 2026.9.4、Hermes 0.21.3、WorkBuddy 5.5.6 |
| 安全边界 | 私有 HOME/Go 缓存/状态/工作区；无 sudo、全局 PATH 或系统安全策略更改；无推送/发布 |

## 修复与测试

此前卸载/重装按“产品名 + `hook <platform>`”子串识别钩子，可能覆盖或删除同一已归属配置里仅**打印**该字样的用户命令。规格先增补所有权规则；实现提交 `450fe18` 改为只识别最新安装记录中的二进制、平台和状态目录生成的精确命令，兼容旧版未给二进制路径加引号的命令；桌面 `status` 也要求记录与实际 hook 相符。CodeBuddy、WorkBuddy 负向回归模拟用户打印产品命令：连续安装两次后每事件各保留一条用户钩子和一条产品钩子，卸载后用户配置原样、状态不误报；当前/旧版真实命令均受正向测试。不能精确证明归属的未知旧变体仍需人工恢复，不用模糊匹配删除。

[verification.json](verification.json) 记录全量 Go `go test ./... -count=1`、`go vet ./...`、gofmt、adapterinstall race 与四目标 CGO=0 交叉编译均通过；跨编译不替代其他 OS 实机，也不恢复已取消的 Intel/macOS 验收。

## 原生宿主与材料矩阵

| 当前候选 | 直接原生通过 | 缺口 |
| --- | --- | --- |
| [OpenClaw](evidence/openclaw-managed-native.json) | 17 项 smoke 通过；八项能力中的 discovery / normal_execution / pre_execution_denial = **3/8** | 本候选未重测失联、最终换参；批准继续、可信 Skill 归属、安装前拦截无原生证明 |
| [Hermes](evidence/hermes-cli-runtime.json) | 6 项 smoke 通过；相同三项 = **3/8** | 同上，真实宿主 hold/retry 能力未证明 |
| [WorkBuddy](workbuddy-attempt.json) | 本候选桌面能力 **0/8**；隔离项目配置安装/状态/卸载及原有非产品钩子保留已核对（不是桌面工具调用） | 桌面发送控件不可用，未产生新回执；旧 P10 候选虽有 3/8 桌面项，不能跨二进制计入；resume、同次 Skill 来源、安装前拦截仍缺宿主通道 |

[18 行清单](manifest.json) 保留 macOS/amd64 `not_run` 和其他 OS 未测行，未删除以制造全绿。结构与证据摘要校验 [退出 0](structure-report.json)，`--require-native` [退出 3](native-report.json)；仓外私有根与本归档目录复验一致，两个引用文件经 SHA256 校验。材料验证器不证明内容真实性或正式支持；合成模型/操作者不是用户真实审批。

WorkBuddy 尝试仅限已有隔离项目配置、受控工作区与 47614 端口；发送不可用时未改变权限或系统安全策略，也未计任何新本机工具调用。之后用本候选卸载产品钩子，Pre/Post 各保留一条原有非产品钩子，停止仅 47614，既有 47612/47613 未操作。日常配置 SHA256 为 `89e179cfe920c2ee4f8956f291ebc0013955071fbd75d320b1ffa410d37541fa`，与前批一致。配对码、token、私钥、账号原文、绝对用户路径及桌面截图均未归档；原始私有状态未提交。

## 按任务书还未完成的部分

- Mac-P02：新候选 WorkBuddy 真实允许/越权/失联需重新走通桌面；OpenClaw/Hermes 的同候选失联和最终参数变化，以及三宿主可信 Skill 归属、批准后继续、原生安装前拦截尚无完整证据。
- Mac-P03：旧 v1 macOS 程序对新状态的真实拒写、注销/登录、重启/休眠窗口及完整失败恢复未全部实测。
- Mac-P04：真实通知点击导航、宿主批准/拒绝后的安全恢复和完整用户旅程仍缺；正式签名/公证不能由开发构建代替。
- Mac-P05/N09：当前 arm64 宿主组合尚未达到 A01–A12 全旅程与独立审阅，故不能关闭。Intel/macOS 属用户取消范围，保留未测而非阻塞或 pass。
