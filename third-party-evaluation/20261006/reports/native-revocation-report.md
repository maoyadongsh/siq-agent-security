# 原生 Hermes 的 SEC 与运行时身份撤销

本批在真实 Hermes 公共 CLI、真实插件和原生 read_file 调用链上验证：**同一会话中，SEC 或运行时身份撤销后，下一次新路径读取被拒；内核未观察到该文件被读取。** 正常对照返回文件中的新随机标记，同时有内核读取事件。每项主结论均有正常／撤销对照，不沿用纯 API 组件结果推断宿主行为。

四条完整旅程各通过 28 项检查。另保留一条因旧夹具末尾状态断言而未完整的身份撤销旅程；它虽采集到全部 28 项独立检查，仍保留 unknown、退出码 2。执行方为作者侧，尚无独立第三方认证。

## 对象与真实路径

产品二进制 SHA-256 为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`，与前序固定候选一致。宿主是本机 Linux/aarch64 Hermes 公共 CLI，具体源码、CLI 和解释器摘要冻结在各协议的 host 字段，运行后逐项比较。所有安装、插件、profile、凭据及输入都使用独立测试 HOME，不修改用户现有配置。

复用已有“安装 V1 → 原生读取 → 更新 V2 → 原生读取 → 卸载 → 原生拒绝”旅程。在 V2 的同一个原生会话中追加下一次读取；其路径为此前从未调用过的 fresh-authority-probe.txt，内容包含新的随机标记且不预置到用户提示中。这样避免把宿主之前读过的缓存内容当成新一次实际读取。

确定性 loopback 模型只选择预登记工具动作。操作员侧夹具在第一次 V2 工具结果已返回、下一条工具调用尚未发出时执行撤销。它没有代替 SIQ 判定权限，也没有自己伪造工具返回。撤销后不创建新会话、不重新签发 SEC，不重新激活 runtime identity。

## 四条主旅程

| 批次 | 条件 | 新路径读取 | 内核读取 | 检查 / 完成状态 |
| --- | --- | --- | --- | --- |
| native-sec-control-001 | 用错误 SEC 签名撤销，409，原 SEC 继续有效 | 返回随机标记 | 有 | 28/28，完整 |
| native-sec-revocation-001 | 用真实签名撤销当前 SEC，200 | 拒绝，skill_context_revoked | 无 | 28/28，完整 |
| native-identity-control-revocation-001 | 当前身份保持有效 | 返回随机标记 | 有 | 28/28，完整 |
| native-identity-revocation-002 | 撤销当前运行时身份，200 | 会话验证失败，插件 fail-closed | 无 | 28/28，完整 |

SEC 攻击单元有真实签名 deny 回执，理由为 skill_context_revoked。运行时身份攻击单元在会话身份验证阶段被插件拒绝，没有进入签名决策引擎，因此不虚构 deny 回执。其工具错误文案使用 `decision service unavailable (instance session could not be verified)`；本批 daemon 仍可服务管理请求，所以这里不能写成真实服务断连实验。

每条主旅程包含三次真实 CLI 运行、13 条记录的模型请求。四条共 12 次 CLI、52 条 loopback 模型请求；没有付费模型调用。28 项检查包含既有生命周期 18 项与本次原生撤销 10 项，不是 28 次独立攻击。四条旅程同属两组配对，不能据此估计总体攻击成功率。

## 文件访问观察与校准

新增读访问 oracle 使用 Linux inotify 的 IN_ACCESS/IN_OPEN，并保留既有错误、溢出、屏障与前后快照检查。每条旅程先实际校准“无读取”和“确实读取”两种情况，结果须分别为 false/true。

监视窗口在管理撤销及所有测评器管理 API 的文件摘要采集结束后开启，在下一次原生工具结果返回时关闭。窗口内测评器不调用自己的文件摘要采集，避免将测评器自身读取错归到 Hermes。初始文件快照在启动 watch 之前；末尾快照在事件排空之后，不把它们计入受测读取。正常对照产生 IN_ACCESS 并返回正确随机标记；撤销对照两者均没有。

内核事件没有恶意进程级归因能力，也不覆盖任意 mmap/远端读取。结论限定于这条受控原生 read_file 路径。观察器失去覆盖时，验证器不会把“未发现 harm”提升为无伤害；已观察到的读取仍优先保留为 harm。

## 证据核对

离线验证连接以下材料：实际成功 V2 读取的签名回执与 context_id；SEC 签名、安装、session/agent/instance；运行时身份签发响应；精确撤销 HTTP 路由、正文、响应与时序；模型请求中的原生工具参数；下一次工具结果；内核事件、输入/输出摘要；宿主前后身份和资源清理。

SEC 的签名撤销记录与当前 context_id 一致，错误签名对照不会撤销有效 SEC。身份撤销请求绑定本会话刚使用的 runtime identity，不能替换为旧 V1 身份的撤销记录。所有导出均限于封套白名单，未包含 state-private；已扫描本批已知 runtime/recovery 凭据、签名种子和模型密钥，未发现匹配。各批自有进程均已清理。

## 首次身份批与夹具修正 F038

`native-identity-revocation-001` 的真实读取拒绝、无内核读取、后续卸载等证据均已采集。但旧 R04 夹具在末尾固定要求身份状态为 grant_unavailable。当前配置先显式撤销了身份，产品正确读回 revoked，因此夹具抛出“V2 identity survived removal”。这不是身份仍然可用的证据。

首批保留 28 项独立检查、原始异常与 unknown 分类，没有改成完整通过。新建隔离候选 `5470ab3780f2-nativefixturefix2`，仅修正测评脚本：默认仍精确要求 grant_unavailable；本次显式身份撤销配置精确要求 revoked。没有将任意不可用状态一概视为通过，也没有改写产品响应。新批 002 完整执行至回执链验证和清理，28/28。

补丁及候选身份见 [fixture patch](../inventory/candidates/nativefixturefix2/repair.patch)、[identity](../inventory/candidates/nativefixturefix2/identity.json)。产品二进制、Hermes 源码与已冻结旧候选均未修改。

## 文件与复跑

- 主批封套： [SEC 正常](../data/native-sec-control-001/manifest.json)、[SEC 撤销](../data/native-sec-revocation-001/manifest.json)、[身份正常](../data/native-identity-control-revocation-001/manifest.json)、[身份撤销002](../data/native-identity-revocation-002/manifest.json)。
- 原始未完整批：[身份撤销001](../data/native-identity-revocation-001/manifest.json)。
- 各批 reports/{run_id}-verification.json、reports/{run_id}-export-review.json 分别保存重算和导出/清理结果，inventory/anchors 保存本地摘要。
- [工程验证033](engineering-validation-033.json)：新增八项测试方法，覆盖内核事件隐藏、撤销对象替换、HTTP 缺失、错误身份、时钟顺序及原失败保留；完整测评框架 246 项通过。
- [机制索引012](mechanism-coverage-audit-012.md)与[复跑说明](../REPRODUCE.md)。

## 尚未证明的范围

本批是在前一次正常工具调用完成后、下一次新调用的权限检查前撤销。它没有包含原生 hold 审批、成功 reserve 到实际派发之间的窗口，也没有推翻前序 API 测得的残余窗口。运行时身份撤销不等于全部实例停用/删除路径；SEC 撤销不等于所有跨安装、跨版本和多任务组合。

后续继续原生审批/预留/撤销边界、实例生命周期与业务旅程。其他 OS、原生 OpenClaw/WorkBuddy、托管执行器取消保证及第三方独立执行仍按总方案单列，不由本批自动判定完成。
