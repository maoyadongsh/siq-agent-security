# 个人 Skill 辅助连接与 24 小时会话

后续状态：用户授权部署后，已完成[本机个人端切换与浏览器验证](personal-skill-connect-deployment-20260925.md)。下文“未替换在线实例”保留开发验证时点，源码提交与签名发行状态不变。

用户要求降低 Skill 安装后的个人管理台使用门槛，并将管理会话改为 24 小时。本轮是 `main@7b68c14` 上的未提交增量，不改变此前 `0.3.1`、本机 `0.4.0-rc.2` 签名制品，也没有替换在线个人或企业实例。[候选与证据绑定](../evidence/personal-experience/skill-connect-20260925/candidate.json)。

## 实现

- 新版页面提供“通过智能体连接”：用户主动发起，将公开请求编号交给本机 SIQ Skill，CLI 明确确认后原浏览器自动进入；不在聊天、URL 或浏览器存储中传递管理令牌。
- 请求有效期 5 分钟，绑定独立 HttpOnly / SameSite Cookie；其他浏览器、决策凭据、过期请求和重复领取被拒绝。确认与领取均先写审计，审计失败不建立会话。
- 管理会话改为固定 24 小时，刷新不续期，退出、重启或到期后需重新连接。新增 `local-admin-session/v2`，不改写 v1 的 12 小时上限；前端兼容两者。保留手动配对。
- 按 Skill 编写规范更新日常使用、明确确认和可信安装路径；按 React 规范将连接副作用放在用户操作中，并防止取消、卸载或其他配对后的迟到响应恢复旧连接。连接浏览器不产生业务 Grant。
- README 中英文、操作指南、规格、ADR 与安装成功提示同步；不更改 README 的主要结构。

## 验证与复现

从仓库根执行（Go 与 Python 命令需切换到所示子目录）：

```bash
# apps/agentshield
gofmt -l cmd/agentshield internal/server
go vet ./...
go test ./...
go test -race ./internal/server ./cmd/agentshield -run 'TestBrowserConnect|TestSession|TestRenewPairing|TestLocalSession|TestLocalInstance|TestLocalUI|TestConnect'
# 仓库根
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web run build:local
python3 scripts/check_capability_honesty.py
python3 scripts/repository/check.py --base origin/main
git diff --check
# apps/control-api
uv run pytest app/tests/test_schema_contracts.py -q
uv run ruff check ../../scripts/personal-experience/browser-connect-smoke.py
```

Go 测试与 vet、前端 55 文件 / 305 项、企业及本地构建、新旧合同校验通过。四目标 `linux/amd64`、`linux/arm64`、`darwin/arm64`、`windows/amd64` 编译通过；交叉编译不代表原生运行验收。

浏览器脚本使用自建二进制及独立状态目录：

```bash
.tmp/k001-browser-venv/bin/python scripts/personal-experience/browser-connect-smoke.py --binary .tmp/browser-connect-20260925/siq-agent-security --out-dir .tmp/browser-connect-20260925/browser-final
python3 scripts/release/skill_source_smoke.py --binary .tmp/browser-connect-20260925/siq-agent-security --target linux/arm64 --report .tmp/browser-connect-20260925/skill-source-final.json
```

复现时使用新的输出目录，不覆盖既有记录。浏览器 9 项通过，见[脱敏报告](../evidence/personal-experience/skill-connect-20260925/browser-report.json)。覆盖桌面和 375px 手机宽度、异浏览器拒绝、取消、显式确认、24 小时 Cookie 与刷新不续期、退出、手动配对、重启失效及无 JavaScript 错误。会话期限通过后端时间边界及浏览器 Cookie 校验，不宣称实际持续运行 24 小时。

Skill 自扫描与源码发行边界 smoke 通过。通用 Codex Skill 校验器不接受本项目已有的 `author`、`compatibility`、`version` 元数据，不能直接用于本产品；保留产品字段，以项目准入和发行检查为准。浏览器最初因 GPU 截图与代理继承失败，脚本显式关闭 GPU、设置独立直连 context 后通过；失败目录保留在本机 `.tmp/browser-connect-20260925/browser-v1` 至 `browser-v3`。

## 尚未覆盖

本轮未提交或发布，不替换原签名包；没有重启在线个人服务或更改现有身份、Grant、企业实例。macOS/Windows 原生安装、真实宿主 Skill 对话全旅程及签名升级/回滚未由本轮验证。历史 12 小时长跑记录仍按原候选解释，不将其改写成 24 小时验收。
