# 个人安装访问与复现准备（2026-09-25）

用户要求其他人安装后能复现个人端体验。本批修复“服务健康但浏览器不在服务机器上，loopback 链接打不开”的安装指引缺口，并扩展干净状态验证。**尚未生成包含本批改动的新签名安装包，不宣称第三方安装已验收。** [候选绑定](../evidence/personal-experience/install-repro-20260925/candidate.json)。

## 本批结果

- `start/serve`、后台安装、`setup` 和 `ui` 给出同机/远程访问指引。远程模板显式绑定客户端 loopback，转发两端端口相同，SSH 登录目标由用户填写；程序不执行 SSH、不改监听范围和鉴权。
- SSH 会话或 Linux 无图形桌面时，`ui` 健康校验后输出指引，不在服务器尝试打开浏览器；`ui --print` 保留单行 URL。
- 按 skill-creator 的范围与明确授权原则，Skill 先区分浏览器/服务机器，连接确认始终在服务机器执行，不猜测 IP/登录凭据，不把公开请求编号当凭据。
- 打包工具生成的 `INSTALL.md`、中英文 README 和操作手册同步。历史已签名 ZIP 字节保持不变。

## 验证

以下命令通过：

```bash
# apps/agentshield
gofmt -l cmd/agentshield
go vet ./...
go test ./...
# 仓库根
python3 -m unittest discover -s scripts/release -p 'test_*.py'
python3 scripts/release/skill_source_smoke.py --binary .tmp/install-repro-20260925/siq-agent-security --target linux/arm64 --report .tmp/install-repro-20260925/source-smoke.json
.tmp/k001-browser-venv/bin/python scripts/personal-experience/browser-connect-smoke.py --binary .tmp/install-repro-20260925/siq-agent-security --out-dir .tmp/install-repro-20260925/browser
python3 scripts/check_capability_honesty.py
python3 scripts/repository/check.py --base origin/main
git diff --check
```

Go 全量、发行工具 18 项、浏览器 9 项通过；Linux amd64/arm64、macOS arm64、Windows amd64 交叉编译通过。源码 smoke 从临时空状态分别验证 `start` 与 `init→serve`、健康识别、手动配对、SSH 环境指引、自定义端口、单行 URL 兼容及正常停止；当前 Skill 自扫描通过，缺签名的源码 bootstrap 继续拒绝。只模拟 SSH 环境来检查输出，不声称实际隧道或另一台电脑已验证。

通用 Skill 校验器因项目既有 `author/compatibility/version` 字段不兼容而失败，保留产品元数据，使用项目自己的准入检查。两个发行 Python 文件的 Ruff 检查有 6 项既有告警；已对比 HEAD，数量与类型一致（5 项 E501、1 项 UP017），本批未新增，不记作 lint 全通过。

## 让别人从安装包复现的剩余门槛

1. 审阅并提交本轮连接、24 小时会话与安装指引增量，取得固定源身份。本轮尚无新的提交指令，不创建提交、标签或推送。
2. 使用原发行信任根构建全新版本的完整离线签名候选，包含匹配的二进制、Skill、清单和安装说明；不能覆盖 `0.3.1` 或 `0.4.0-rc.2`。
3. 对最终解压包验签及四目标 pin 检查，在支持的原生平台以空状态走完安装→打开→确认连接→刷新→退出；分别记录同机访问与真实两机 SSH 访问。当前仅有 Linux ARM64 源码候选验证，其他平台不能借用其结论。
4. 公开发布需独立授权及下载回读；本机完整离线候选可以在验证后作为限定范围的测试交付，未公开上传前不能承诺 Skill-only 下载可用。

当前在线实例仍为此前已部署的 `0.4.0-dev-connect`，本批仅补 CLI/安装指引，未再次重启或更改实际用户状态。企业端未改动。
