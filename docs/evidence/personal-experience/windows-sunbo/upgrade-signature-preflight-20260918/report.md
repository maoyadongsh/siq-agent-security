# Windows 原生升级预检签名拒绝补充

使用既有干净 de5 Windows exe（具体源码和二进制摘要见 verification.json），仅初始化本批私有状态。未启动服务、未切换版本、未调用模型。输入来自仓库 skills/siq-agent-security/skill-manifest.json；它是现有 v1 签名清单，不伪装为 v3，也不重签发布材料。

## 复现与结果

复制清单并使用明确 UTF-8 解码。原始语义对照，以及签名首字符、末字符、全零签名、binary.version 篡改四类独立副本，分别运行：

`agent.exe client-upgrade-check --manifest <本批副本> --binary <实际de5候选>`

原对照退出1，诊断为 signed client compatibility declaration missing or unsupported。由实际实现的检查顺序确认它已通过签名检查，随后被升级兼容声明门禁拒绝；这不是升级预检成功。四个篡改副本均退出1，诊断 signature mismatch，stdout为空。每次调用前后比较全部状态目录文件摘要/目录条目，均一致；源清单和源二进制摘要也未改变。只保留隔离状态和证据文件，无后台进程或监听器创建。

首轮控制器按 Windows 默认文本编码读取 UTF-8 清单，改变 support_matrix.note 中的字符，导致原对照同样 signature mismatch。该轮无效对照保留在本机 upgrade-signature-r1，不作为通过依据；r2 明确 UTF-8 后才取得有效对照。没有通过改清单签名、绕过验证或改生产代码修复夹具问题。

## 边界

这只证明现有 v1 签名清单在真实 Windows CLI 预检入口的篡改拒绝。未证明 v3 清单、合法升级/回退、实际制品摘要不符或运行服务切换。P03-STATE-20 保留完整要求未验收状态，附此部分证据；不能把兼容声明缺失当作状态不兼容或真实摘要拒绝通过。其他项与303分母保持不变。
