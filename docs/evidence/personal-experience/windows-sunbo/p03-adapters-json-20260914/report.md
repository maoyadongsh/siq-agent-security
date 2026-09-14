# Windows policy-exec 测试输入修正

两处测试直接把原生 Windows 路径拼入 JSON，反斜杠使请求在进入预期检查前解析失败。本批改用标准 JSON 编码，保留 target/source 字段、原生路径和 block/warn/allow、admission/verdict 断言；负向用例明确区分 malformed、缺少路径和不是可读目录，并先确认 file-not-dir fixture 确实是现有普通文件。仅一个测试文件变更，没有新增 Skip 或修改生产代码、宿主协议。

干净基线 `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 在 Windows 完整包测试为 4 pass / 1 fail；干净修复候选 `94e0d162215cb4238f0759cb96cae4a99f437b48` 聚焦 2 项及完整包 5 项全部通过，无跳过或超时，模块 gofmt 与 vet 通过。根代理独立核对五阶段原始/派生长度、SHA256、事件及候选身份；另有独立源码审阅，无必改项。完整命令、失败前证据和限制见 [实测报告](results/report.md)。证据提交身份与受测代码身份分开。

此处 policy-exec 按规格 4.1 是外部宿主接口的组件测试，不证明当前 OpenClaw 原生安装拦截、真实宿主工具调用或 WorkBuddy 桌面闭环。本候选未重跑 Windows 全模块测试；[PR #48](https://github.com/maoyadongsh/siq-agent-security/pull/48) 记录的 `2f84d5a…` Windows 模块失败仍保留，不重标到本候选。完整 Go 模块测试及四目标构建须另看当前 PR 最终 head 的 CI，交叉构建不等于原生系统验收。Windows/N09 总体仍未完成。
