补充 Windows 最小补丁建议（尚未实现或复验）：

`state.DefaultDir()` 当前通过 `product.Env` 读取状态目录，而后者先执行 `strings.TrimSpace`。因此尾空格在文件层检查前已经丢失，仅给 `statefs` 或父目录检查增加拒绝条件会漏掉该输入。

建议在规格 §2.1 定义 Windows 状态目录输入规则，再由 Windows 专属 helper 在任何 Clean/Abs/Join 前检查原始环境变量及显式 `serve --state-dir`，拒绝实际路径组件尾 ASCII 空格/点。保留全局 `product.Env` 和非 Windows 语义，不静默 trim、迁移或回退到另一个实例；正常中文、内部空格、导航组件及已支持的长路径继续适用现有规则。直接 Open、兼容检查和 Writer 入口复用同一校验，hook 保留结构化 block。

原始实机复现仍见 PR #44，绑定旧候选 `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`，不能重标为补丁验证。本次静态检查固定 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`；刚抓取的 main `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 在上述 state/signing/statefs 及 serve 入口范围无差异。

拟回归覆盖主/旧变量、非法主变量不回退、中间组件/尾分隔符、已存在 alias 不修改、显式 serve 不启动、直接 state API 与 hook 结构化拒绝，并验证有效路径保持原行为。#39 的资源规范化和 #42 的 ACL 不由此补丁关闭。

按共享协作规则保留一个主修，请维护者/GLM 确认共享状态调用点的主修或交由 Windows 负责人实施；sunbo 可承担 Windows helper 与原生负向复验。此评论为可审阅方案交接，未修改共享运行代码，也不声称问题已修复。
