# F06：E11 修复后候选的 Linux/Hermes 原生 SEC 回归（2026-09-17）

独立隔离配置中以真实 Hermes Agent v0.21.0 公共 `hermes chat --oneshot`、真实插件钩子与文件工具运行，模型端点为本地确定性 fixture。使用修复 E11 后重新构建的 SIQ Linux/arm64 二进制 `0b16e5e0…6c8177`；[候选源绑定](candidate.json)记录未提交树的 931 个 Go/mod/embed 文件摘要，测试报告记录宿主 CLI 与脚本摘要。

命令：`python3 scripts/personal-experience/r01-sec-hermes-native-smoke.py --binary /tmp/siq-v6-hermes-post-e11-agent --hermes-cli /home/maoyd/.local/bin/hermes --out <本目录>/sec-native.json`，退出码 0，[结构化结果](sec-native.json) `passed=true`、11/11 检查、4 个回执、2 个已验证决策。覆盖两个已安装 Skill 的权限隔离、管理员任务级 SEC、原生允许读取与禁止写入、调用绑定重算、跨任务 SEC 复用拒绝和签名链验证。脚本 `TemporaryDirectory` 清理隔离 Hermes HOME；启动观察插件是测试同步器，不提供 SIQ 权限。私有 console 日志位于忽略的 `native-private/`，目录 0700、文件 0600。

这只关闭**此候选 Linux/Hermes 原生 SEC 回归腿**。脚本未创建原文 Grant，也未验证自然到期后的原生新调用，不能写为 F06 完成。最新修复候选没有重跑真实网关 D05、完整浏览器 E12 或排他性能；不能把旧候选的这些结果转移过来。Windows/macOS 仍按 sunbo/Luke 各自实机证据独立验收。
