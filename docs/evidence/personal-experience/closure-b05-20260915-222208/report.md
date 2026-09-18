# B05 证据报告 — 服务失联时真实宿主 fail-closed 与零独立副作用 (2026-09-15)

## 1. 范围
- 真实宿主: 公开入口 `openclaw agent --local` (OpenClaw 2026.5.12), 真实插件 hook 生命周期
  (managed 安装, runtime identity, block 模式), 本地确定性模型 fixture 驱动多轮工具调用。
- 任务旅程: 服务在线正控 (授权写真实落盘) → 停止 SEC daemon → 必要调用全部拒绝 →
  audit_only 降级覆盖仍 fail-closed → 同端口重启 + 重新配对 → 离线 pending 晋升到签名回执链
  → 授权读恢复。
- 独立副作用通道均为具体物证: 文件用专属 marker 路径; 网络用进程内 loopback 接收端
  (不进 fixture 端点白名单, 只有真实 curl 子进程能命中)。

## 2. 关键事实
- 接收端先自证计数 (harness self-test 1 hit), 之后全程 hit 数不变 — 所有"零 egress"断言
  都建立在已证明工作的接收端上, 排除"端点不通"假阳性。
- 服务在线时: 授权 write 执行且 marker 内容精确匹配 (正控证明"授权→宿主工具真实执行")。
- exec 契约: `runtimeaction/normalize.go` 对 exec 类工具无条件附加 unknown effect
  ("a text command can delegate to arbitrary programs"), `intent/matcher.go` 因此必然
  `runtime_effect_unknown` 拒绝 — up-leg exec 通过真实宿主收到该 service decision 拒绝回执
  (1 条, deny), 且零 egress。即: shell 出口不存在授权放行路径, 失联拒绝对 exec 而言
  与在线拒绝同向 (更严格)。
- 服务失联时 (daemon stopped): write/read/exec 全部被插件 fail-closed 拒绝;
  down marker 不存在; loopback 接收端 hit 数不变 (零独立副作用);
  4 条 pending 记录 `pending_decision/v1`, `signed:false`, `outcome:deny`,
  `enforcement_mode:block`, reason 前缀 `decision service unavailable (`, platform=openclaw。
- audit_only 降级覆盖: managed 安装下改写本地 enforcementMode=audit_only, 写仍被拒绝,
  pending 照记 — managed 路径不信任本地模式字段。
- 恢复: 同端口重启 + 一次性配对码重新配对; 4 条离线 pending 全部晋升为
  `promoted pending fail-closed` 前缀的 deny 签名回执; DOWN_CALL_IDS 全程无任何授权回执;
  恢复后授权 read 放行且读到受保护 fixture 内容; promotion cursor == pending 行数;
  `agentshield verify` 链验证通过。

## 3. 覆盖与遗漏
- 16 项检查全部 done, 见 checks.json; 无登记缺口。
- 遗漏声明 (limitations, 非 gap): 本宿主无可用授权 egress 放行路径 (exec 类永不兼容 intent,
  无原生 loopback web 工具), 故"授权 egress 执行"正控由授权 write 承担,
  egress 通道证明零副作用属性 (任务书要求的方向)。

## 4. 隔离与安全
- 全程 TemporaryDirectory 隔离 HOME/state (0700) 与 workspace; daemon/model/接收端均绑 127.0.0.1;
  本地确定性模型, 无付费模型或生产端点; 未触碰真实 ~/.config/siq-agent-security 与
  ~/.openclaw; 无 bypass、无断言放宽、无系统时钟改动; 未 commit/push。

## 5. 复现
```
python3 scripts/personal-experience/closure-b05-service-down-side-effects.py \
  --openclaw-root <openclaw> --node <node> --binary <agentshield> --out <report.json>
# 本次: exit 0, {"passed": true, "checks": 16}
```
- 二进制 sha256 22b867384f6e074489a7b0b37b085120f082bf12e06822d8af19570c8dca3d92
  (harness 现场构建); OpenClaw CLI sha256 ee861ae6f3298a0c2062ff52a682b5ce4786ae515a3eb816921f9a128341c733。
- 过程日志仅保留 run.log (无敏感字段); journey 原始报告 b05-journey-report.json。
