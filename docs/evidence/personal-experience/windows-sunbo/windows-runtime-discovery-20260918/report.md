# Windows 运行检查与发现合同开发证据

本包归档已有的定向开发检查，不执行新测试，不代表真实宿主验收或最终干净候选通过。所有检查保持 `source_dirty=true`，不修改 303 台账，也不新增验收 PASS。

## 源码身份与结果范围

检查后由集成负责人提供的完整提交定位引用如下。v5 实现于归档任务发起时尚待独立审阅，归档期间已完成审阅提交；这不改变此前开发检查的源码状态，不能倒写成在这些提交的干净源码上运行。

- 合同：`3d19833d5119a4edaf44007327da3ec659a56605`。
- inventory：`001b64408023c8153163ff7df79f38ff2a000a07`。
- v5 实现：`7a9c8d89678263e82e5c56fb8926cb3891d633cf`。

发现接口使用固定 `72140795963244d293232c905a34ef00312b8253` 模块副本，加唯一的 `discovery_http_test.go` 测试补丁。`logs/inventory-discovery/r2/fixed-module-source.json` 保留 1,337 个普通文件的来源摘要、唯一补丁摘要及 13 份相关生产文件的一致核对；回收前又核对一次，只回收指定四个官方生成 JSON。此副本不包含随后开发的 runtimecheck v5。之后的 inventory `manifest` 修复不改变 discovery preview/status 的行为，因此不重复这部分检查。

inventory 的 r1/r2 在当时集成开发源码上运行，r4 才包含最终 Evidence 类型修复。其归档时源码摘要在 `inventory-source-after-checks.json`，不能反推成各轮运行前的完整源码快照。runtimecheck v5 的 `source-sha256-after-checks.json` 同样明确为检查后捕获；本包保留原值，不伪造运行前固定身份。

## 结果及计数

| 类别 | 最终可陈述结果 | 原记录 |
| --- | --- | --- |
| v5 r1 | gofmt 及五包 `-run ^$` 编译 exit 0；0 个实际测试用例 | `logs/runtimecheck-v5/r1/summary.json` |
| v5 r2 Go | 29 个唯一顶层用例 PASS；按 `(Package, Test)` 跨日志去重 | `go-top-level-results.json` |
| v5 合同与静态检查 | 独立 1 个 Schema 用例通过；Ruff、五包 vet 均 exit 0 | `logs/runtimecheck-v5/r2/summary.json` |
| inventory r4 | 2 个 Go 顶层用例，Windows 与 WSL/Linux 各 count=2，通过 | `logs/inventory-discovery/r4/` |
| discovery r2 | 1 个 Go 顶层用例内检查 status/preview；Windows 与 WSL/Linux 各 count=2，通过 | `logs/inventory-discovery/r2/` |
| inventory/discovery 合同 | 独立 2 个 Schema 用例通过；Ruff exit 0 | `logs/inventory-discovery/r4/schema.json` |

29 个 v5 用例、1 个 v5 Schema 与 2 个 inventory/discovery Schema 分开记录，不用一个累计“通过数”混合口径。样例生成、重复轮次、count=2、不同 OS 和同名用例不会变成额外唯一用例。两个 HTTP 样例也不会算成两个 Go 顶层用例。

runtimecheck v5 用例验证的是受控组件夹具、临时授权及清理、实例与参数绑定、失效/撤销/恢复、审计失败拒绝、HTTP 和适配器边界。测试名称、组件 allow/deny 或签名样例均不能证明真实 Hermes/OpenClaw/WorkBuddy 已执行。原产品 120 秒上限没有扩大；旧测试轮询等待从 5 秒调整到 150 秒是等待原 deadline 和清理结束的测试预算，不是产品执行授权延长。

## 原失败与修复

1. r1 WSL 复制 exit 1：已有发行版禁用 Windows 自动挂载与 interop，`/mnt/c` 不存在；该阶段尚未执行组件测试。失败 stderr 和命令保留。后续只通过 stdin tar 传入自建测试二进制和明确公开样例到新建私有临时目录，没有挂载盘符或改 WSL 配置；WSL 清理命令与退出码一并保留。r2 最初 inventory 传输还包含自行创建的普通目录条目，后续仅传常规文件并显式创建目录；均无链接或用户配置。
2. r2 Ruff exit 1：当时新增的 v5 测试块有 I001 导入间隔和 E731 lambda 赋值问题；由该文件负责人修复，r3/r4 及 v5 r2 Ruff 复验通过。不能将此轮失败删成全绿。
3. r3 Schema exit 1：两个选择用例一过一败，新的 WorkBuddy 目录 Evidence 使用了 `directory_manifest`，该值属于 Candidate 词汇而不属于 Evidence 合同。r4 先补规格，再将生产代码改为现有合法 `manifest`，保持 Candidate 为 `workbuddy_profile`，补选定实例的定位、唯一证据引用及规范化元数据摘要断言后重新生成库存黄金样例。没有扩宽合同枚举、修改生产身份算法或改签旧正式制品。

库存黄金样例原先只固定 Attributes 的实例 ID，而新 WorkBuddy 身份还进入 locator、目录元数据摘要和签名。测试辅助函数先校验原始签名与元数据，再用公开测试键和既有 evidence builder 形成一致的合成身份投影并更新全部引用；其余字段仍参与完整黄金比较。Windows 的真实 Hermes AppData 发现根使用独立样例；Linux 库存检查直接验证共用样例，不把 Windows 输出覆盖为 POSIX 黄金。

## 脱敏、摘要和限制

`provenance.json` 分别列原始和公开文件 SHA256、字节数及映射。原文件未修改；空流仅保留摘要，不提交零字节副本。公开文本统一 UTF-8/LF；Windows 工作区、用户目录、WSL 临时根、发行版标签、SID 和凭据形态以占位符替换。混合 WSL stderr 严格按 UTF-16LE 提示前缀和 UTF-8 命令错误分段解码，不丢弃错误文字。

元数据内部既有摘要仍指原始字节，不能用于比对脱敏后的公开文本；公开摘要以 provenance 和 SHA256SUMS 为准。公开包没有二进制、私钥、账号会话或日常配置。`validation.json` 仅是对这个证据包的摘要、格式、计数和隐私形态核查，不是产品测试或新的秘密扫描工具结果。

本包未完成真实三宿主旅程、WorkBuddy 桌面/项目实际加载、最终干净候选完整回归、正式发布签名、另一设备验收、维护者合并或发布；这些边界继续由各自任务和真实证据负责。
