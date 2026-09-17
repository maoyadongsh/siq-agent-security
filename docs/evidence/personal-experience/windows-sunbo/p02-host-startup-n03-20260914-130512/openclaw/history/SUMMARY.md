这些记录来自 Windows 宿主上的 WSL2/Linux。五项配置预检通过；A 首轮及两次诊断均未观察到 provider 或工具回合，纯 namespace 探针通过。这些结果不构成 Windows 原生 OpenClaw 或 SIQ 完整旅程验收。

| 历史批次 | 实际执行 | 退出与观察 |
|---|---|---|
| preflight | Node 许可查询及四条 OpenClaw 查询命令 | 5/5 exit 0，子命令 stderr 全空；未执行 agent 回合 |
| A 首轮 | agent --local | exit 1；自有合成 provider 已启动，请求 0；工具回合未观察到 |
| diag02 | agent --local，增加被动错误观察 | exit 1；请求 0；捕获六条非致命 PATH 探测拒绝；未实测致命 resource |
| diag03 | agent --local，观察器补充 existsSync | exit 1；请求 0；另实测两次 existsSync('/tmp') → ERR_ACCESS_DENIED / FileSystemRead |
| namespace | 单线程纯探针 | exit 0，7/7 检查通过；没有执行 OpenClaw、Node、SIQ 或 provider |

所有这些子命令均无 timeout，已 wait 回收。A/diag 的自有 provider 线程和两个 socket 均已关闭；目标前后不存在、控制哨兵与固定源码/Node 摘要不变。A/diag 未加载 SIQ，原 agent_turn_invoked=null 保留为未知，不能把目标未创建或权限拒绝记为 SIQ block。B 在这些历史批次中未执行。

预检配置验证保留退役 default 标记警告；旧配置前后未改。A/diag 使用新配置省略该字段。所有 wrapper 的 WSL 传输 stderr 均非空，含 localhost/NAT 提示和混合编码；它与子命令 stderr 分开记录，不能写成“全部 stderr 为空”。

namespace 的七项检查覆盖子探针成功、有界回收、父 namespace 不变、父 /tmp 元数据不变、合成内容正确、哨兵不变及 unshare 文件摘要不变。实测单线程降权后四组 capability 全零，NoNewPrivs 保持开启；不外推 OpenClaw 多线程宿主。

summary.derived.json 是白名单衍生件，列出每批原始 wrapper SHA、存储 stdout/stderr 文本摘要、版本与源码身份及精确局限。只保留公共 resource 常量 /tmp，其他资源替换为分类；不含完整 argv/env、原始日志/堆栈/请求、私有路径、OS 身份、签名或凭据。原件保持私有且未改写；衍生件不供原始签名验证。摘要只覆盖上述五批，后续新 A 材料不在本快照内。
