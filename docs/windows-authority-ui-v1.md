# Windows 路径授权界面增量

沿用 windows-authority-runtime-v1.md 的后端授权与状态升级合同。

- 旧 Grant 打开编辑器时保留原 POSIX 解释，不根据浏览器系统、宿主名称或输入路径自动升级。仅支持的 managed 实例授权显示 Windows 本地盘符解释选项；选择后还需明确确认，才发送 grant-resource-edit/v2 和 confirm_filesystem_profile=true。保存仅产生 pending 修订，批准仍是后续独立操作。
- 已签入 Windows 解释的 Grant 显示其 profile，不能在编辑器切回旧解释；未知/不完整的版本与 profile 组合不能编辑或用于身份签发。Windows 路径按换行分项，只忽略完全空行，保留前后空格、反斜杠、大小写和 Unicode；只读快捷操作同样不 trim 路径。后端决定路径是否合法，UI 不悄悄修正尾点、尾空格等别名。
- Runtime Identity v1/v2 摘要可在列表中混合显示；新身份的 Windows 解释另有人工确认，确认绑定所选实例、Grant 及 revision。刷新、换授权或权限变化后需要重新确认。只有新 Grant、有效确认和 create/v2 共同出现才发送 confirm_filesystem_profile=true，不通过旧 create/v1 降级。
- Scope 摘要和现有身份显示所使用的文件路径解释。批准或身份签发仍不等于真实宿主加载、实际保护或 OS 沙箱。
- 未完成状态升级时显示后端固定错误的诊断提示，引导先查看 state-status 和保留状态；界面不执行升级、提权、重启或绕过兼容屏障。其他权限或资源错误不能伪装成状态升级问题。
- profile 降级与身份确认的作用域校验同时位于提交逻辑中，不能只依赖下拉框或按钮禁用。身份确认绑定平台、实例、Grant ID、正整数 revision 及 profile，不能复用一般权限核对的确认值；未知版本或缺失 revision 拒绝继续。
- Node 单元测试覆盖上述提交边界、真实请求序列化及固定错误分类，不宣称浏览器点击、焦点管理或真实宿主验收完成；这些交互仍在集成阶段验证。
