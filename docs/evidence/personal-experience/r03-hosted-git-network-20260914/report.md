# R03（N02）公共 Git 真网前置检查

- 时间：2026-09-14T19:31:00+08:00
- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- 候选源码基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2` 加本工作树未提交 R01/R02 差异
- 证据类型：网络环境前置检查；不是 GitHub 正向下载或原生 Skill 导入证据
- 结论：**blocked，生产 Git 门禁继续关闭**

## 观测

在当前 Linux 环境使用系统解析器查询真实目标域名，得到：

| 域名 | IPv4 结果 |
| --- | --- |
| `api.github.com` | `198.18.0.29` |
| `codeload.github.com` | `198.18.0.4` |
| `github.com` | `198.18.0.8` |

`198.18.0.0/15` 是基准测试保留地址范围，不是允许公网下载的目标。现有受控 HTTPS 传输会在连接前
拒绝该地址，符合 SSRF/DNS 重绑定防护。未修改 hosts、DNS、代理或公网校验，也没有向这些解析结果
发起绕过保护的请求。

## 处置与解除条件

`productionGitFetch` 继续返回 `skill_import_git_transport_unavailable`，Web Git 入口继续禁用。本批没有
删除 503 门禁，也没有把 fixture 测试改称真网通过。

解除条件是在能把 GitHub 三个域名解析到真实公网地址、且允许直接 TLS 连接的环境中，按
[ADR-0051](../../../adr/0051-controlled-hosted-git-source.md) 对同一固定候选执行公开仓库 ref/commit/子目录、
上游前进、固定 commit 不变、404/不可访问仓库及重定向/DNS 变化负向验收。完成后才能单独评审把
`productionGitFetch` 接到 `fetchHostedGit`。
