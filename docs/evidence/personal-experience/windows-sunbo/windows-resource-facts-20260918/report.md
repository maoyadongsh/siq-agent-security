# Windows 原生资源事实层（#39 接续）

干净源码 `d384e24690c8514fe4671dc39d255e7e86a566fc`，main基线 `bb364015f745316497f0d654ee9746b5287035c0`，叠加PR82到897c477。复用历史合同5f54dcb与词法8cbeea2，接续为b335421/0b6e5be；原工作树保留。PR83为草稿，不关闭#39。

## 实际变化

旧版词法入口仍保持POSIX签名语义；新增事实检查独立读取本地固定NTFS卷和逐组件句柄，核对规范DOS/NT长名称、设备映射、大小写属性、单链接和删除状态。只允许最后一个叶子缺失。保存每级身份后重新检查，目标/父目录替换、叶子出现及链接状态变化拒绝。

句柄申请只读数据/目录枚举权限以参与Windows共享检查，但不读取文件内容。检查期间禁止DELETE共享；仅属性句柄不能提供同样保证。开发负向发现该差异后修正，并用真实rename失败/释放后成功证明句柄效果。删除负向使用FileDispositionInfo建立真实待删除状态，未把早期delete-on-close夹具误判为既有生产漏洞。

## 已完成的验证

- Windows原生runtimepath：10顶层、2子测试通过，零skip。包含中文/空格、新叶子、大小写及8.3别名、真实junction、多硬链接、父/目标替换、占用、待删除、句柄期间改名和大小写敏感目录。对象均为隔离夹具。
- runtimeaction整包：24顶层、54子通过。旧Intent v2/v3真实签发读回及权限兼容：1顶层、20子通过；不可变签名字节保持。
- 新包与runtimeaction的race检查退出0。fmt无输出、vet退出0。
- 主程序Windows amd64、Linux amd64/arm64、Darwin arm64构建退出0；内嵌SHA一致、modified=false。新包尚未被生产调用，因此另行对该包四目标test -c，均退出0，未冒充其他OS原生执行。
- Python新旧合同校验233项通过。候选Schema样例使用零签名，仅证明结构，不证明授权有效。
- 完整Go命令 `go test -json -p 2 -count=1 -timeout=45m ./...` 在独立冻结源码树运行；以full-go-status.json的时间点状态为准，不能称整模块通过。

## 尚需完成

新版Grant、Runtime Identity、Intent及session绑定的明确批准、兼容写入屏障和最终参数复验仍须接通。需解决签名授权范围与现场文件身份的绑定，而不是只在Describe阶段打开新profile。之后固定新集成候选完成真实Hermes/OpenClaw允许/拒绝/失联/撤销和审批重试；WorkBuddy另遵守桌面能力及单次额度限制。

事实层不创建Authority、不持久化新合同、不改变旧Grant或session，不宣称新profile已启用。检查结束释放句柄，宿主执行前仍有同UID TOCTOU；不是OS沙箱。不将组件证据计为A04通过，唯一台账仍73/303通过、3失败、5受阻、222未测，3系统中断排除。

## 复现与清理

在上述干净源码的apps/agentshield运行 `go test -count=1 ./internal/runtimepath ./internal/runtimeaction`，以及 `go test -count=1 -run TestLegacyFilesystemRegexDoesNotGainWindowsAuthority ./internal/intent`。使用独立TEMP/TMP和已有私密测试父目录；夹具权限不冒充产品ACL能力。race使用本机GCC与CGO_ENABLED=1，其余交叉构建使用CGO_ENABLED=0。原始输出私有保留，公开JSON仅摘录测试身份和结果。

测试移除junction、还原临时目录大小写标志并清理TempDir；无daemon、真实宿主、模型调用、提权、全局盘符更改或系统中断。完整回归仍占用其独立测试目录，未声称该运行中资源已经清理。

后续终态：冻结 d384e24 完整 Go 回归退出1，1346顶层通过、55失败、70跳过；28包通过、14失败、7跳过。原始日志摘要及完整失败列表见 full-go-status.json。此前“运行中”仅为当时时间点，不再是当前状态。
