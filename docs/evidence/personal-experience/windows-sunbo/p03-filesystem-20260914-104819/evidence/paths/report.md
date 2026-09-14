# Windows P03：路径、文件共享与恢复观察

本批在原生 Windows 11 25H2 / NTFS 上复用干净实现候选 `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` 的 amd64 二进制，SHA-256 为 `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74`。运行时 checkout 为 `973541733ccdb25d4578e56033901e4829ff257c`，仅含上批证据增量；运行前后 clean，Go 模块与候选没有差异。没有改产品代码或原有状态。

**真实缺口 WIN-STATE-PATH-001：`init` 接受尾点、尾空格的目录输入，并在去掉尾字符后的 OS 别名目录初始化，未向操作者显示实际路径。** 这是输入被接受并解析为另一路径拼写的观察；本批没有证明产品代码主动执行 strip、目录逃逸、权限绕过或目录身份混淆攻击。

## 结果与计数

原始 [results-20260914.json](results-20260914.json) 保留 **14 例、9 pass / 5 fail、41 次 CLI**。其中两例是上述真实路径偏移，三例来自初版共享冲突证明不足；不能把原报告改为全绿。[sharing-results-20260914.json](sharing-results-20260914.json) 在三个新的私有 fixture 中完成 **9 次 CLI、3 例 pass**，改用第二次原生 CreateFileW 调用确证 ERROR_SHARING_VIOLATION=32。两轮不是两个独立的完整 14 例平台验收。

| 用例 | 实际观察 | 可支持的结论 |
| --- | --- | --- |
| 中文与空格 | init、state-status、同参数重复 init 均退出 0；真实目录句柄路径匹配输入，实例身份保持 | 本次初始化路径正确 |
| 盘符大小写 | 先使用原拼写初始化，再改小写盘符和重复调用；目录与实例身份相同 | 当前 NTFS 组合中的盘符别名没有生成第二个实例 |
| 尾点 `target.` | init 退出 0，实际相对路径为 `target`，精确输入匹配为 false | **未满足任务书“不悄悄截断/重写到另一条路径”要求** |
| 尾空格 `target ` | 同上：产品接受，实际为 `target` | **同类缺口** |
| `NUL` | init 退出 1；状态诊断退出 0；目录、文件/流、属性及安全描述符摘要无变化 | 当前设备名用例明确拒绝且无持久变化 |
| `CON.txt` | init 与重复调用退出 0，实际目录句柄路径与输入一致 | 本例允许创建该目录，不推导其他设备名、运行命令或系统管理器均支持 |
| 冒号组件 `target:stream` | init 退出 1；全例目录/默认流/命名流快照不变 | 该缺失状态目录的 ADS 拼写被拒；不是所有已有文件 ADS 攻击的证明 |
| 长路径与显式扩展前缀 | 两例 init/重复调用/诊断均成功，最终路径未截断，身份保持 | 仅初始化与诊断路径可用；计划任务路径限制需另测 |
| config、state-format、local-instance 被独占 | 补充三例中第二次 CreateFileW 均返回 32；产品 init 均退出 1；句柄正常关闭后 init 均退出 0 | 操作系统分享锁有效，产品拒绝并在释放后恢复，已有持久状态保持 |
| config、state-format ReadOnly 属性 | 同参数 init 退出 0，已有内容与属性/安全描述符摘要不变 | init 保留现有配置；不是只读文件替换、发布或 DACL 隔离验收 |

结合补充证明，可说 **14 个行为场景中 12 个满足上述限定预期，2 个存在路径别名缺口**。这只是当前路径/初始化范围，不是完整 P03、A10 或三宿主八项检查的通过率。

所有 9 个路径用例的 `state-status` 均退出 0，调用前后快照相同，由补充报告的独立断言逐项核对。退出 0 不等于状态兼容；状态 JSON 的 compatible/status 另行保留。尾点/空格的 compatible=true 也不能消除输入路径偏移。

## 测量修正与独立审阅

初版仅记录 `sharing_violation_proved=false`，没有记录当时 Python CRT 异常的 errno/winerror。因此无法从原记录单独确定该 false 的具体原因。补充报告中的 `initial_lock_reason` 将其归因于 CRT 未保留错误码，这是**原因假设，不能当作旧次现场事实**；应以“初版未取得原生共享冲突码，新增原生复验已确认有效；旧测量具体原因 unknown”为准。两个原始 JSON 与执行脚本均保留原字节，没有覆写旧结果。

[independent-review.json](independent-review.json) 记录独立只读复核：扩展路径下精确 `target.` / `target ` 不存在，正常 `target` 可打开，普通输入与实际目录文件身份相同，排除了仅观察器规范化的假象。补充共享锁证据包括原生错误码、产品拒绝、CloseHandle 成功、释放后恢复及前后完整持久快照。

快照枚举普通文件与 NTFS 命名流，记录内容摘要、文件名、mode、link count、Windows attributes 和 owner/group/DACL 二进制描述符摘要。没有记录 SID 原文、文件内容或时间戳。快照相等只证明观察点之间的持久状态一致；init 本身会取得并释放 Writer 锁，**不证明没有瞬时写入尝试**。

## 复现与范围

执行源码为 [probe.py](probe.py) 和 [sharing-recheck.py](sharing-recheck.py)，各结果记录对应脚本摘要。它们是本批实际执行脚本，保持原字节；在独立干净 checkout 中复现时，需将二者复制到 `.tmp/windows-next-draft/paths/`，并按原调用布局准备 `.tmp/win-p03-next/paths` 的私有 NTFS 父根及 `.tmp/win-task-native/build/siq-candidate-windows-amd64.exe`。第二脚本固定引用第一轮结果文件名；原目录已有结果时必须使用新的独立 checkout，不能覆盖历史输出。

第一轮从仓库根运行（binary 需匹配上述摘要；私有父根必须先核对 DACL）：

```powershell
$env:PYTHONUTF8 = '1'
& 'apps/control-api/.venv/Scripts/python.exe' '.tmp/windows-next-draft/paths/probe.py' --binary '.tmp/win-task-native/build/siq-candidate-windows-amd64.exe' --test-root '.tmp/win-p03-next/paths' --out '.tmp/windows-next-draft/paths/results-20260914.json'
# 本候选实际 exit 1；保留结果后执行原生分享锁补充，实际 exit 0。
& 'apps/control-api/.venv/Scripts/python.exe' '.tmp/windows-next-draft/paths/sharing-recheck.py'
```

原探针含有已记录的测量局限，作为复现原始运行的材料保留，不表示推荐继续使用其 pass 汇总逻辑。后续可复用工具应把诊断退出码/中间快照纳入直接判定、将全部独占句柄操作包在 finally 中，并把路径查询失败单列为测量错误；本轮没有发生未记录的查询异常。

没有启动服务、计划任务、浏览器或智能体，没有模型/付费调用。所有命令均使用自建二进制和明确隔离状态。未测另一卷、受控 UNC 共享、签名版本排他发布/rename 竞争、权限跨用户访问、真实迁移或断电恢复。私有 fixture、原始命令输出和失败现场均保留；未手工删锁或清理未知对象。
