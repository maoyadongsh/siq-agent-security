# R04-C 最终本地候选集成复验

- 日期：2026-09-14
- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- Git 基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`
- 未提交候选二进制 SHA256：`10dedfb776d736c838593b28d24cac77e06eb2788615a74cd4c5f3ae9f46d617`
- 构建输入：`git ls-files --cached --others --exclude-standard -- apps/agentshield apps/web` 中当前存在的 1225 个文件；逐文件 SHA256 清单的组合摘要为 `d0bbf2cf624fc398b97d5580cd003ef451319029f2508bd35b5a80b52dd71db8`
- 状态：本机集成复验通过；未提交、未推送、未合并、未发布

## 结论

在修复 R02 未结案 reservation 的 24 小时清理缺陷后，重新构建的 Linux/aarch64 最终本地候选通过 7 项更新事务和 30 项会话、发现、适配器及断连恢复检查。两条 runner 都使用真实候选、隔离状态/profile 和真实 Chromium；Hermes 额外使用本机真实 `hermes` CLI 对隔离 `work` profile 完成原生插件配置启用、诊断与卸载读回。

这次复验证明本批后端修复没有破坏个人管理与更新流程，也证明 Hermes CLI 能对指定隔离 profile 原生登记和移除当前插件，同时保留默认 profile 与用户后续配置。它没有启动 Hermes/OpenClaw 模型，没有执行真实工具调用，因此不关闭 R01/R02 的原生调用门槛，也不把插件配置就绪称为运行保护通过。

## 更新事务：7/7

`skill-update-browser-smoke.py` 通过以下检查：

1. 未批准 V2 只展示内容与权限差异，V1 保持不变。
2. 准备更新后刷新仍要求重新核对。
3. 桌面和移动宽度均可完成最终确认。
4. 丢失提交或读取响应后不盲目重放写操作。
5. 查询恢复成功结果，旧 Grant 撤销，新 Grant 不自动激活。
6. 完成页刷新零写入且新版权限入口正确。
7. 后续更新资源耗尽时显式中止，保留上一版本与权限。

## 会话、发现与适配器：30/30

`session-browser-smoke.py --discovery --hermes-cli /home/maoyd/.local/bin/hermes` 通过原 28 项检查，并增加：

- `native_enable_applies_only_confirmed_profile`：真实 Hermes CLI 只修改用户确认的隔离 `work` profile，默认 profile 逐字节不变；插件文件落在该 profile 下。
- `native_uninstall_preserves_other_profile_and_later_user_settings`：卸载只移除 SIQ 登记及插件文件，保留用户在安装后新增的配置与其他 profile。

其余检查覆盖一次性配对、Cookie/跨标签会话、同名 Skill 分离、重复扫描身份稳定、手动范围、移动端、预览取消零写入、未知文件保留、WorkBuddy 独立未验证、配置并发变化拒绝覆盖、禁用插件诊断、重启重新配对与服务恢复。

## 边界与后续

- Hermes CLI 配置登记是真实原生命令行为；运行时插件加载、SEC 同调用绑定和批准后工具重试仍需实际宿主工具调用。
- 更新来源为隔离合成 Skill/API 旅程；公网 Git/ZIP 仍受当前网络解析阻断。
- WorkBuddy Linux 运行时不存在，Windows/macOS 实机由对应协作者继续。
- 没有使用模型、修改日常 Hermes/OpenClaw profile、发布制品或发起公网请求。

