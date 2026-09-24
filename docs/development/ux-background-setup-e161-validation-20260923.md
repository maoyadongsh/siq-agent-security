# E161 DGX Spark 后台接入交付验收

本轮完成 Linux ARM64 后台接入体验候选，修复首次后台启动和 Hermes 重复接入两个实际阻碍。**可供本机体验，尚不是正式签名发行或整项目生产交付。** 本轮停止扩展功能；后续任务独立列出，不把增强不断加入本次交付。

## 交付物与使用

下载本机体验包（本机私有路径：`var/flagship/ux-e161/siq-agent-security-linux-arm64-preview-e161.tar.gz`）。包内含安全控制台、中文说明、完整性摘要和许可证，共 94 个文件。只适用 Linux ARM64；使用独立状态目录，不替换原安装。固定包 SHA-256：

```text
2bbcd0af065001f5e3c6c389567cba48d5c891eca442bc72f80ed0e995708949
```

解压后进入 `siq-agent-security-preview`，执行：

```bash
export SIQ_AGENT_SECURITY_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/siq-agent-security-preview-e161"
./siq-agent-security setup --confirm-setup --runtime --port 18171 --open-ui
./siq-agent-security pair
```

在页面输入配对码，依次发现框架、选择角色和 Skill、检查权限并确认接入。发现不代表已经受保护，以接入状态和运行验证为准。后台运行无需保留终端，当前方式不配置登录自启。无桌面时用 `./siq-agent-security ui --print` 获取本机地址。无 systemd 用户管理器时可用 `start --port 18171` 前台运行。

新终端须重新设置相同状态目录。`service-stop --confirm-stop` 停止服务；`teardown --confirm-teardown` 注销并保留身份和记录。退出使用前，先在控制台卸载实际框架的接入组件，避免 block 模式因决策服务停止而拒绝工具。程序运行时不要移动解压目录。

## 实际修复

1. **首次后台启动失败**：服务准备提前创建自身锁文件，使初始身份保护误以为已有历史且签名密钥丢失。现先在主 Writer 下建立身份，再按原锁顺序重载并比较公钥。已有历史丢钥、损坏密钥和并发写入仍拒绝，不自动重建历史身份。
2. **Hermes 卸载后重新接入失败**：原生命令规范化 YAML 并保留用户新增配置，字节不再等于首次恢复副本。现限定同实例、同配置根、已提交且认证成功的原生卸载；副本必须匹配认证历史内容。旧卸载未读取副本时最多回查 64 条历史的已提交安装封装。原始副本不重写，实时配置中的用户设置保留；篡改副本和操作摘要均拒绝。

浏览器验收最后一处失败来自 YAML 字节比较。已改为配置语义比较，只允许格式、Hermes 版本标记和空插件容器规范化；用户字段变化及残留非空注册仍失败。前台旧测试继续保留字节比较。

## 验证结果

| 范围 | 结果与证明边界 |
| --- | --- |
| 真实后台浏览器接入流程 | **53/53**；发现、角色/Skill 分类、检查、中文权限选择、审批读回、两框架安装卸载、越权与撤权拒绝、记录及结果入口、375/768px 和键盘操作 |
| Hermes 原生工具与页面 | **12/12**，另 **8/8** 后台生命周期检查；真实原生加载/工具分发、安装钩子、允许读取、拒绝写入、受控采集和准确正文 |
| OpenClaw 原生工具与页面 | **12/12**，另 **8/8** 后台生命周期检查；真实原生加载/工具分发，after relay 由测试驱动调用；未声称模型完整会话 |
| 后台生命周期 | 实际 systemd MainPID/程序摘要/HOME/状态目录、重复 setup 不换 PID、端口冲突拒绝、受支持停止/重启、同身份新 PID、注销和同状态重入后记录保留；浏览器旅程另 **7/7** |
| Go | `go test ./...` **44 包通过**，实际 Hermes CLI 用例启用；`go vet ./...`、改动文件 gofmt、关键测试 race 通过 |
| 平台构建 | Linux ARM64 原生及 Linux AMD64、macOS ARM64、Windows AMD64 交叉构建通过；后三者不等于原生体验验收 |
| 最终压缩包 | 93 个内容文件的摘要逐一校验，加摘要文件共 94 个；解压二进制新状态启动、配对、页面、停止通过；同二进制真实 setup 专项通过 |

全部最终测试使用二进制 `c8503564f5082d4ffd8984c51fc4810a9d386b7638b32e4ad6875843aefefbe3`。先前失败与中间二进制日志保留，但不算最终通过证据。本轮不改 UI 产物；使用已有控制台，增加后端修复和真实后台验收。

测试仅操作独有临时 HOME、状态和 runtime 用户单位，合成文件不涉及业务数据。服务完成归属核对、注销及清理后才移除夹具；共享 systemd manager 环境保持原样。未替换用户已安装程序、改实际模型/profile、迁移业务数据库或调用云模型。

复现主要命令（仓库根执行浏览器脚本，Go 命令在 `apps/agentshield`）：

```bash
SIQ_HERMES_NATIVE_CLI=/path/to/hermes go test ./...
go vet ./...
SIQ_HERMES_NATIVE_CLI=/path/to/hermes go test -race ./cmd/agentshield ./internal/adapterinstall -run 'TestServicePrepareBootstrap|TestServicePrepareBootstraps|TestHermesNativeCLIStagesEnableAndRestoresOnlyOwnedSettings'
SIQ_TEST_SETUP_SYSTEMD=1 SIQ_TEST_BINARY=/absolute/path/to/siq-agent-security go test ./cmd/agentshield -run '^TestNativeSetupAndReuse$' -count=1
python scripts/personal-experience/environment-onboarding-browser-smoke.py --binary /path/to/siq-agent-security --openclaw-root /path/to/openclaw --node /path/to/node --background-service --out-dir /new/output/directory
python scripts/personal-experience/native-runtime-output-browser-smoke.py --binary /path/to/siq-agent-security --hermes-root /path/to/hermes-agent --background-service --out-dir /new/hermes/output
python scripts/personal-experience/native-runtime-output-browser-smoke.py --binary /path/to/siq-agent-security --platform openclaw --openclaw-root /path/to/openclaw --node /path/to/node --background-service --out-dir /new/openclaw/output
```

## 明确结束线与后续任务

**本次本地体验候选已完成。** 正式发行交付仍须独立完成安装/升级包的发行信任与升级验收，以及用户实际环境的接入确认；本包不冒充正式签名安装包。研究业务运行目录/结果页源码及构建沿用 E160，尚未部署在线 API/Web。

原总目标继续保留未完成项：生产 IAM 与业务授权、正式业务端到端故障/恢复、最终 DGX 原生 CI 门禁、跨应用身份连接及其他 OS 原生验收。批量管理等增强和 SEC-F01–F10 按任务书后续清单处理，不在本轮增加范围，不以候选通过清零。没有提交、推送或发布。

[规格](background-setup-acceptance-e161-spec.md) · [证据](../evidence/flagship-optimization-20260921/ux-background-setup-e161.json) · [任务书](user-experience-onboarding-taskbook-20260923.md)
