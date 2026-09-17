# A09：Node API 对照成立，OpenClaw 宿主验收仍未完成

2026-09-15 06:12（Asia/Shanghai），在 Windows 宿主现有 WSL2/Linux x86_64 内，以普通 UID1000 完成三个自建 Node 24.19.0 文件 API 探针。实际进程退出依次为 0、1、0，诊断完整，预设假设得到支持。本批未启动 OpenClaw、SIQ、provider 或模型；A09 是本轮诊断编号，不表示任务书的 Windows 路径验收项已完成。

| 探针 | 实际调用和结果 | 文件读回 |
| --- | --- | --- |
| D0 | 独占 staging→写入→fstat/lstat 身份检查→close→rename→读回；exit0 | 目标29字节、SHA匹配、mode0600、单链接；staging不存在 |
| D1 | 同样步骤在 `await FileHandle.chmod(0600)` 处拒绝；exit1 | 目标不存在；staging保留准确29字节；close成功 |
| D2 | 同位置改用 `fs.promises.chmod`，随后close/rename/读回成功；exit0 | 目标29字节、SHA匹配、mode0600、单链接；staging不存在 |

D1 精确到达 fd-chmod，未返回成功；前四阶段完成。原错误的 own code 为 ERR_ACCESS_DENIED，permission/resource 均为 present 空字符串，未截断；name/syscall 为 absent，stack 未读。消息匹配标志表明它等于本探针预先固定的“启用 Permission Model 时 fchmod API 被禁用”消息。原始结果分别见 [D0](D0-probe.json)、[D1](D1-probe.json)、[D2](D2-probe.json)，未把预期失败的实际 exit1 改写为0。

这些控制说明，本批环境和权限下基础写入及路径chmod可完成，句柄chmod有特定拒绝。它们不证明 A08 实际走了相同 backend/API，也不是完整 fs-safe fallback 重放。A08 仍是实际 write 失败；其 cause 仅关联同一受控进程，没有唯一调用绑定。不得据此把路径chmod替换判定为安全产品修复，或删除句柄/身份安全检查来获得宿主通过。OpenClaw A 未新增成功，B 未运行。

实际读回验证两个新 namespace、仅映射原 UID/GID、私有挂载传播，以及 owned tmp 的相同设备/inode。Node启动前 CapEff/Prm/Inh/Amb均为0、NoNewPrivs=1；原始父 namespace和/tmp元数据前后相同。Node保留 permission，仅读包目录、本批runtime与私有/tmp，仅写后两者；没有 child/worker/addons 权限。每项原网络日志重新解码，恰好一条 native-permissions 事件，旧profile读写与进程扩展权限均false。guard只覆盖所选Node公开网络API，不能称为OS网络隔离证明。guard preload可在stdin token前写权限日志，探针文件操作等待token。

三个Node约0.407/0.417/0.415秒自然退出；namespace约2.093秒，Windows主传输约2.583秒。每项等待回收完成，无超时/强杀/收尾错误；两个只bind不listen的本批socket已关闭。Linux回收由guest报告，Windows传输wait/dispose另有记录，不从一个外层exit推定全部清理。fixture全部保留。预算为单项10秒含3秒收尾、批次75秒、parent110秒含5秒收尾、Windows150秒含10秒收尾，不保证任意阻塞OS调用可被硬抢占。

[核验索引](verification.json)绑定18条原流：Plan4、Run4、后置只读2条Windows流，namespace2和Node6条guest流。Base64、长度、SHA、解析对象与后置同名文件摘要一致；三个网络日志及17个指定自有文件另有只读读回，3个应缺席路径均缺席。Windows主stderr保留132字节WSL localhost代理/NAT提示，原driver使用UTF-8 replacement、decode_error=true；补充严格UTF-16LE解码不能抹去原状态。它不同于三个Node均为空的stderr。

r2先成功Plan，Run在unshare旧摘要校验处失败，Linux根未创建、Node未启动；原件保留在 [r2拒绝摘要](r2-refusal.json)。A08实际使用过旧摘要，本次只读包记录显示util-linux从2.39.3-9ubuntu6.4升级到6.6，当前root-owned0755文件匹配安装包MD5。r3仅更新parent中的一个预期unshare SHA，其余五份源码字节不变；新Windows目录单独保留r3。此为本地包记录和文件观测，不声称独立验证包签名或确认更新发起者。

运行身份以[汇总](summary.json)中的Node/package/unshare摘要及[五个实际载荷](verification.json)标识；公开材料不含第三方源码正文、日常配置、私有绝对路径、PID/SID或原始状态。PR55文档上下文在实验期间为clean bd38a1f20470bdefb0dae2c01f09cc999199abdc，不是Node或SIQ执行身份。原18行平台矩阵、研究分母及WorkBuddy native_desktop缺口不变。本批没有产品代码修复，不声称安全修复回归或Windows整体完成。
