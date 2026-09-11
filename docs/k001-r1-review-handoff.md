# KIMI-001 审阅补修 R1：当前接力状态

参考 HEAD：`8b53ddff0463efed2fe56d62954d382f3dbb163e`。原六个提交保留；在 `kimicode/personal-k001-baseline-repair` / PR #27 追加补修，不修改 main、不合并、不发布、不改治理设置。

## 已落实的最小修复

1. Hermes 内嵌适配器改为与运行时源码同一个 Git blob `581932d05dfdfac84b605259f89f66985b81677e`。保留 `TestEmbeddedAssetsMatchRuntimeTree`，不删除逐字节一致性检查。对应上一轮 ci run 34567835675 和 runtime-security run 34567835676 的已观察失败。
2. `SecureApplication.run` 在计时、run ID 分配、目录/文件创建、Grant、模型和网络操作之前验证 `confidential_name`；仅支持当前已有的两个操作者夹具名 `.env` 和 `confidential-note.txt`，非字符串和其他名称统一拒绝。默认和两个既有测试夹具保持不变；保留下游 TaskAuthority 和工具层路径/内容校验。该参数不是新的 HTTP 或模型权限入口。
3. 新增 `test_confidential_preflight.py` 两个测试方法，涵盖两种 trifecta 状态下的 52 个无效输入子用例和 4 个支持名称子用例。旧实现的无效输入用例由运行分配 tripwire 提前终止，不真正写越界文件。

## 依据与范围

原个人任务书第 4.3、6.1、10.2、13 节要求：检查前置、授权与副作用分离、正负向成对、证据不夸大。本次为 KIMI-001 既有新增夹具参数的输入收紧与遗漏副本同步，不改变 Go 引擎、Grant/Intent 合同、共享规则、历史快照或外部产品范围。不为消除测试失败而授予凭据读取权限。

## 已运行与未运行

当前审阅执行环境无法解析 github.com，完整 clone 未成功。通过 GitHub 连接读取精确 SHA 的源码并提交；不能声称在此环境完成全仓构建或真实 daemon/平台测试。

入口检查使用 Git blob 校验一致的原文件，抽取实际 run 方法并以首次计时为后续操作 tripwire：52 个拒绝、4 个支持输入检查通过；旧方法在无效输入时越过前置校验位置；新增 Python 文件语法检查通过。该检查是隔离入口检查，不是完整应用、Go、HTTP 或跨 OS 验证。新测试的真实导入与全量结果以对应 PR 候选的 CI 为准。

## 仍然阻塞合并的审阅项

`skills.py` 捕获 Blocked 后根据人类可读 reason 前缀继续研究的行为尚未修改，不能因本次 CI 变绿而默认验收。必须分开验证：凭据读取被拒且执行器未进入；允许读取的非凭据合成机密文件如何经既有可信机制建立安全状态；之后的不可信输入与外发如何被拒。不得把“拒绝尝试的保守污点”声称为“成功读取后的信息流”。

这部分需要在完整本机检出与隔离真实 daemon 中追踪决策/观察和测试含义，并同步当前测试/演示说明。另需核对草稿并发测试是否确定性地证明在途提交等待：现有撕裂状态测试不是活跃并发窗口的替代证据。

状态：`partial_repair / awaiting_ci / semantic_review_blocked`。后续 Kimi 任务只处理本批剩余补修及最终证据，不开始 KIMI-002、新 Hermes 更新功能、LAN 或发布。历史交接中的 awaiting_ci、本地全绿及未推送等描述只对应当时的代码/阶段，不作为本候选通过证明。
