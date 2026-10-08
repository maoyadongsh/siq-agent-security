# OPT-15：Linux 本机未授权拒绝与重启

日期：2026-10-08。任务保持 **implementing**，总体 **11/16（68.75%）**。

当前二进制 `aa25999e` 在新建隔离状态中 `init` 后 `serve`。没有部署 Grant，没有调用模型，临时状态已删除。

| 请求 | 结果 |
| --- | --- |
| 不带凭据的 `write_file` | HTTP 401 `unauthorized` |
| 未知 Bearer | HTTP 401 `unauthorized` |
| 决策凭据，无 Grant 的 `write_file` | HTTP 200 `deny`，`grant_missing` |
| 同一凭据的工具名 `write` 和 `opt10_unmapped_tool` | 同样是 `grant_missing` |
| `stop --confirm-stop` 后再次 `serve` | 健康检查 200，凭据不变，写入仍拒绝 |

目标文件没有创建。`verify --chain local` 报告 4 条回执、`head_seq` 3、`verified` true，链头 `ae628bea30523f390b72d4c194901cfa80a20b5f885cdaaf49070c73c85f3aa7`。

`write` 与未映射工具的拒绝原因是没有 Grant，不能当成已授权 `write_file` 下的别名隔离。这不是签名安装、企业升级或 Windows/macOS 验收。

证据：[linux-daemon-deny-recovery-20261008.json](evidence/optimization-20261007/linux-daemon-deny-recovery-20261008.json)。
