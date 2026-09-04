# openclaw-agentshield（OpenClaw 适配器：L1 安装门禁 + L2 运行时）

两半：**安装门禁**由 OpenClaw 的 `security.installPolicy` 调用 `agentshield policy-exec`（Go，在本仓 `apps/agentshield`）；**运行时**由本目录的插件把 `before_tool_call` / `after_tool_call` 接到决策 API。两半都不含规则、判定或密钥。

## L1 安装门禁

`~/.openclaw/openclaw.json`：

```json5
{
  security: {
    installPolicy: {
      enabled: true,
      targets: ["skill"],
      exec: {
        source: "exec",
        command: "/usr/local/bin/agentshield",   // 绝对路径
        args: ["policy-exec"],
        timeoutMs: 10000,
        trustedDirs: ["/usr/local/bin"],
        passEnv: ["AGENTSHIELD_STATE_DIR", "HOME", "PATH"]
      }
    }
  }
}
```

`policy-exec` 读 stdin 的安装请求，对 `stagedPath` 跑 `agentshield admit`，输出：

| admission verdict | decision | 说明 |
| --- | --- | --- |
| `quarantine` | `block` | reason 列出隔离类别 |
| `admit_with_conditions` | `warn` | 提示安装后 `agentshield grant <admission_id>` |
| `admit` | `allow` | |
| 请求畸形 / 无路径 / 分析失败 | `block` | fail-closed（OpenClaw 在 exec 失败时同样 fail-closed）|
| `targetType != skill` | `warn` | 插件安装不在本策略范围 |

准入结论与 Skill Card 同时写入 AgentShield 状态目录，控制台可见。

## L2 运行时

```bash
agentshield adapter install openclaw
# writes ~/.openclaw/plugins/agentshield/ and merges security.installPolicy into openclaw.json (backup first)
```

| 决策 API `action` | 插件返回 |
| --- | --- |
| `allow` | 无决策 |
| `deny` | `{ block: true, blockReason }` |
| `hold` | `{ requireApproval: { title, description, severity: "warning", timeoutMs } }` → OpenClaw 审批流；结果由后续调用重新决策 |
| `redact` | `{ params }`（改写后的参数） |

`after_tool_call` 把结果截断 64 KiB 发 `/v1/observe`（服务端脱敏、更新污点）。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 超时 / 401 / 非法 JSON / 无 token | `block: true` | 放行 + `console.warn` |
| OpenClaw 钩子 15 s 超时 | OpenClaw 自身 fail-closed | 同左 |

## 卸载

`agentshield adapter uninstall openclaw` 从 `<state>/backups/adapters/` 还原 `openclaw.json` 并删除本插件目录。

## 验证状态

- `policy-exec`：Go 单测 + 真机冒烟（隐藏注释 Skill → block；官方风格 Skill → warn）。
- 插件 TS：按 OpenClaw 2026-09 `before_tool_call` 合同编写（`block` 终止、`requireApproval` 首个生效、`params` 改写），**尚未在真实 OpenClaw 网关上运行**；E2E 计划见规格 §7.4。
