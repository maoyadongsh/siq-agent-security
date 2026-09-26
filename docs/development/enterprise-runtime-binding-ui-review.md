# ENT-018-BINDINGS-UI 主开发者复核

日期：2026-09-25。范围：Claude Code 运行时绑定 UI 交付的代码、标准前端门禁与隔离浏览器验收；不代表 ENT-018 整体或生产环境验收。

## 已确认并修复的问题

1. 未知状态被页面操作区统一标为“已终态”。改为未知状态提示，不提供吊销操作；revoked 保持终态说明。新增行为测试在修改前失败、修改后通过，不扩大生产状态类型。
2. 登记请求在途仍能编辑选项/目标或收起表单，可能导致显示输入与提交快照不一致。请求期间禁用表单输入及收起，失败后恢复可编辑并保留输入。新增行为测试先失败后通过，浏览器增加在途/失败恢复验证。登记 API 载荷不变。
3. 375px 吊销弹窗长目标 ID 在弹窗内部溢出；原先页面级宽度断言未覆盖它。实际查看 r2 截图确认。ConfirmDialog 增加可选 className 并透传现有 Modal；绑定页专用 rb-explorer-revoke-dialog 样式使用 overflow-wrap:anywhere。没有修改共享 CSS 或其他弹窗默认样式。浏览器增加 dialog/title 内部宽度检查。
4. 吊销期间虽然按钮禁用，Escape 仍能经 Modal 关闭窗口。绑定页关闭回调在 busy 时不关闭，处理器也拒绝 busy 下再次调用；不修改共享 Modal 的键盘行为。浏览器增加请求在途 Escape/禁用检查，完成后正常关闭。
5. 原浏览器“乱序”夹具给 A、B 相同延迟，不能证明 B 先返回。只延迟 A，并独立记录返回顺序，断言确实 B→A。增加浏览器出站范围拦截及 service worker 禁用；全部请求只允许本次 loopback 合成服务。

另依 React 最佳实践的 effect 清理要求，环境/资产加载 effect 在关闭或卸载时递增请求代次，迟到结果失效。保留既有实例 seq 防竞态。未做无关重构或风格重设计。

## 本次文件

- apps/web/src/pages/RuntimeBindingsPage.tsx
- apps/web/src/pages/RuntimeBindingsPage.test.tsx（新增 2 项）
- apps/web/src/components/ConfirmDialog.tsx（可选样式参数，默认行为不变）
- apps/web/src/components/runtime-binding-explorer/runtime-binding-explorer.css
- scripts/enterprise-experience/runtime-binding-explorer-browser-smoke.py
- 本复核记录

原作者交付记录保留，不将历史结果改写成主开发者的独立验证。

## 验证记录

- 原始工作树 npm test：101 文件 / 839 项通过。
- 新增回归先执行：14 通过、2 失败，分别准确命中未知状态和登记在途未禁用。
- 修复后页面测试：16 项通过；全量 npm test：101 文件 / 841 项通过。
- 初次标准构建因新增负向测试把未知状态传入受限 fixture 类型失败；已改成线响应 mock 的开放对象，不放宽产品类型。随后标准 tsc -b + vite build 成功。
- r2 隔离浏览器 44/44，但人工截图复核发现弹窗内部溢出，未将该结果视为最终验收。
- r3 加入内部宽度断言及局部样式后 44/44；最终含吊销在途检查的 r4 **45/45 通过**，page_errors 和 blocked_requests 均为空。只读阶段零写，业务回归仍只有 2 次登记、2 次吊销合成 POST。
- 最终标准构建成功，`VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false`，输出 `/tmp/siq-bindings-review-production-final-20260925`；最终全量测试 101 文件 / 841 项通过。`git diff --check` 通过。

## 最终证据与结论

浏览器执行命令：

```bash
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/runtime-binding-explorer-browser-smoke.py --output /tmp/siq-bindings-review-20260925-r4
```

- 报告：`/tmp/siq-bindings-review-20260925-r4/report.json`
- 桌面截图：`/tmp/siq-bindings-review-20260925-r4/bindings-desktop-expanded.png`
- 375px 截图：`/tmp/siq-bindings-review-20260925-r4/bindings-375-form-dialog.png`
- 模拟构建日志：`/tmp/siq-bindings-review-20260925-r4/build.log`；临时模拟构建由脚本清理，未发布。

仅本绑定 UI 子任务的源码与隔离交互复核通过，保持原项目主题；不宣称生产 IAM、绑定真实性、OpenShell 执行或防护效果已验收。未提交、未部署。

所有 API 为合成 mock，登记和吊销仅写到临时测试服务器的内存记录；没有使用真实身份、真实设备或真实业务数据。源码修改未改变后端权限、审批、审计、检测规则或防御配置。未提交、未部署。
