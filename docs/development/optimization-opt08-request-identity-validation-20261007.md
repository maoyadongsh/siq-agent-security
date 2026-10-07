# OPT-08 D3c：请求级子身份与原生运行衔接

日期：2026-10-07。状态：真实 HTTP 子身份与 OpenShell 权限链路通过；日常业务入口未完成，OPT-08 保持 implementing，总体 9/16。

## 问题与修复

核对智能分析助手既有请求身份签发器时发现：其会话前缀是 `siq:openshell:pool:{scope_id}:{request_id}:siq_analysis`，而原生 Runtime 与 ImageBootstrap 仅接受不带冒号、最多 64 字符的前缀。此前根身份和短前缀联验通过，无法证明真实请求级子身份可接入。

两入口现在共用严格 ASCII 校验：非空字母、数字、点、下划线、连字符组件可由冒号分隔，总长最多 191 字符。原样保留前缀，与实际 session 的 SHA-256 合成最多 256 字节的会话 ID。拒绝首尾/连续冒号、Unicode、控制字符、空白、非字符串及超长输入。服务端请求范围、批准基线和制品校验没有放宽。

## 同次真实联验

专属 Go HTTP 测试服务通过管理配对创建原生根身份，再由管理员开启现有请求签发能力，父凭据经 `/v1/runtime-identity/self/requests` 签发子身份。检查返回 v2、必需原生制品策略、父身份关联以及 `unverified` 状态。仅把子凭据交给宿主决策转发器，凭据不进入沙箱。

使用子凭据登记错误 namespace 得到 400，登记返回的真实 namespace 派生会话成功。实际 OpenShell 内的受保护初始化器收到完整前缀，沿内核认证通道进入真实 Go Authority，18 项检查全部通过：

- reader 读允许、写拒绝；切换 writer 后仍保持祖先权限交集。
- 独立 writer 合法写成功、越界写拒绝；并发任务权限不串扰。
- 重放及任务结束后调用拒绝；SEC 和 Skill Grant 撤销后拒绝。
- 父 Agent 基线撤销前子身份正常读，撤销后无法读取。

23 次工具尝试形成 18 条已校验签名回执（14 allow、4 deny），另 5 次在决策前拒绝。宿主独立核对文件效果；独有沙箱和网络已清理，原网关配置及 TLS 摘要不变。

## 验证与证据

相关 Python 163 项通过，含真实请求前缀、191/192 长度边界、严格格式拒绝及初始化后前缀保持。真实 fork 负向产生一条预期弃用警告。Ruff、Go 请求身份/原生签发定向回归、server vet 和 diff 检查通过。首次 pytest 命令误写了不存在的测试文件名，收集阶段终止；纠正为实际 `test_native_relay.py` 后完成上述 163 项，无执行失败被忽略。

```bash
var/mako117-20261006/worktree/apps/control-api/.venv/bin/python -m pytest -q \
  adapters/runtime/hermes-agentshield/tests/test_native_bootstrap.py \
  adapters/runtime/hermes-agentshield/tests/test_native_dispatch.py \
  adapters/runtime/hermes-agentshield/tests/test_native_channel.py \
  adapters/runtime/hermes-agentshield/tests/test_native_online.py \
  adapters/runtime/hermes-agentshield/tests/test_native_relay.py
python3 patches/hermes/run_openshell_runtime_probe.py --online \
  --output var/optimization-20261007/opt08-openshell-request-identity-01
# 在 apps/agentshield 下：
go test ./internal/server -run 'TestNative.*(Readback|Enrollment)|TestRuntimeRequestHTTP' -count=1
go vet ./internal/server
```

真实 Go 集成段 21.849 秒。候选制品、源码与原始结果摘要见[结构化证据](evidence/optimization-20261007/native-request-identity.json)。本批 Go 仅改测试夹具，没有重复无关全量和跨平台构建。

操作员、request ID、execution digest 和 Skill 内容仍为受控合成材料；业务仓库只读检查，保留既有修改。此结果证明现有请求子身份协议能贯通原生链路，不证明真实业务 API 授权、执行租约、业务撤权、模型对话或日常网关启动器已验收。下一步必须接入这些真实业务生命周期，而非把探针当作业务入口。
