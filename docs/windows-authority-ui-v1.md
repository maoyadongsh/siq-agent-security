# Windows 路径授权界面增量

沿用 windows-authority-runtime-v1.md 的后端授权与状态升级合同。

- 旧 Grant 打开编辑器时保留原 POSIX 解释，不根据浏览器系统、宿主名称或输入路径自动升级。仅支持的 managed 实例授权显示 Windows 本地盘符解释选项；选择后还需明确确认，才发送 grant-resource-edit/v2 和 confirm_filesystem_profile=true。保存仅产生 pending 修订，批准仍是后续独立操作。
- 已签入 Windows 解释的 Grant 显示其 profile，不能在编辑器切回旧解释；未知/不完整的版本与 profile 组合不能编辑或用于身份签发。Windows 路径按换行分项，只忽略完全空行，保留前后空格、反斜杠、大小写和 Unicode；只读快捷操作同样不 trim 路径。后端决定路径是否合法，UI 不悄悄修正尾点、尾空格等别名。
- 合法输入如 `c:\Users\me\reports` 由明确选择 Windows profile 的后端资源编辑入口规范为 `C:/Users/me/reports` 后签入新 pending 修订；界面继续原样提交输入。后端仅允许盘符大小写和分隔符转换，并在转换后检查每个列表的重复范围；保留组件大小写、Unicode 序列及所有非法路径拒绝边界。保存后展示后端返回的新范围，原签名历史不改写，旧 POSIX 路径不自动转换。
- Runtime Identity v1/v2 摘要可在列表中混合显示；新身份的 Windows 解释另有人工确认，确认绑定所选实例、Grant 及 revision。刷新、换授权或权限变化后需要重新确认。只有新 Grant、有效确认和 create/v2 共同出现才发送 confirm_filesystem_profile=true，不通过旧 create/v1 降级。
- Scope 摘要和现有身份显示所使用的文件路径解释。批准或身份签发仍不等于真实宿主加载、实际保护或 OS 沙箱。
- 未完成状态升级时显示后端固定错误的诊断提示，引导先查看 state-status 和保留状态；界面不执行升级、提权、重启或绕过兼容屏障。其他权限或资源错误不能伪装成状态升级问题。
- profile 降级与身份确认的作用域校验同时位于提交逻辑中，不能只依赖下拉框或按钮禁用。身份确认绑定平台、实例、Grant ID、正整数 revision 及 profile，不能复用一般权限核对的确认值；未知版本或缺失 revision 拒绝继续。
- Node 单元测试覆盖上述提交边界、真实请求序列化及固定错误分类，不宣称浏览器点击、焦点管理或真实宿主验收完成；这些交互仍在集成阶段验证。

## WorkBuddy Windows 受管接入

按 `workbuddy-managed-runtime-spec-v1.md` 接通 WorkBuddy 的实例权限流程。平台能力来自服务端实例目录，不根据浏览器所在系统推断。既有普通配置接入不代表受管身份或真实桌面保护；macOS 旧接入保持既有行为。

- WorkBuddy 实例可以从已有准入起草权限，用户须在资源编辑中明确选择并确认 Windows 本地盘符解释；不自动转换已有 POSIX Grant。身份准备再次绑定当前平台、实例、Grant ID、revision 与路径解释确认。
- WorkBuddy 受管身份仅接受 Windows profile；旧 POSIX Grant 仍可显示，但界面说明须重新起草或编辑权限，不能发送 create/v1 作为降级。Windows create/v2、issued/v2 和 list/v2 使用本轮尚未发布的新合同增量；其他宿主保持原行为。
- 身份签发请求显式携带前端选定平台用于本地响应核对，不增加 HTTP 请求字段。返回平台不一致、WorkBuddy 身份缺 Windows 元数据或 envelope 不匹配均拒绝，不自动重签、重试或退回共享令牌。列表同样拒绝伪装成旧 POSIX 身份的 WorkBuddy 条目。
- 受管配置应用、身份准备或组件检查不能显示为原生桌面保护通过；主任务、子任务与恢复会话的实际覆盖按真实证据单列。

## 从真实检查结果起草实例权限

真实 Skill 准入经普通 `/v1/grants` 产生的 Skill Grant 不能冒充实例 baseline。实例权限面板改用 `POST /v1/grants/instance-drafts` 的 `grant-instance-draft-create/v1`，用户确认作用域用于所选实例后提交 instance_id、admission_id、actor_id、稳定 request_id 和 confirm_instance_scope=true。不提交自报 platform/subject/path；服务器恢复真实实例并派生主体。仅起草 pending 权限，Windows 路径选择、批准和身份签发仍是后续独立步骤。

确认值绑定平台、实例、准入和操作者，选择变化即失效。同一待完成请求保持同一 request_id；失败不自动重试。响应必须匹配实例、准入、平台、派生主体、独立草稿 ID 命名空间且没有 SkillRef，revision 为非负整数（首次创建为 0）；新建须 pending，幂等重放不要求服务器重置已修改的授权。不同响应或未知结果不能直接进入批准。普通 Skill 授权入口与既有签名记录不变。前端定向测试读取 Go HTTP 实际输出投影的合同样例，避免双方对首次 revision 的约定分离。
