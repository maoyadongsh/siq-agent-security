# OpenClaw 实际调用历史的通用导出隐私检查

Windows Companion → 本机 WSL2 OpenClawGateway，不能标作 Windows 原生宿主。本批未重新调用模型或宿主：复用 session-newkey-r1 两次真实原生工具调用及其已保存 SIQ 状态，候选185a0d6、二进制摘要62d820…0ec41，与原宿主实验相同。

## 方法与观察

确认本批历史状态存在且无 serve.lock；拒绝符号链接/非普通文件/多硬链接文件。记录全部38个文件摘要，精确复制到新建0700专用目录的 state 子目录。HOME/XDG 路径指向新的隔离 home，从空工作目录执行同一实际二进制 `export --out <私有输出>`，不指定 Connector、不启动服务、不触碰日常 profile。

产品退出0，导出5648字节、两条回执摘要。导出内返回 chain_verified/chain_prefix_valid/checkpoint_consistent=true、history_integrity=verified、incomplete=false；这些是产品自检字段，本批未额外独立验签导出文档。原始历史目录38文件摘要保持不变。

独立检查整个导出字节：两种已知合成内容、原工作区路径、私有home前缀均0匹配。与本批原始状态的决策 token、admin recovery token、签名种子的原始/去空白、base64和hex形式比对，均未发现；只输出布尔结果，不输出凭据。递归JSON键检查未发现 params、params_excerpt、token、admin_token、signing_seed、command、content。

原始磁盘回执中合成写入文本位于 params_excerpt。规格允许脱敏限长excerpt，通用export明确禁止该字段；本次确认它没有被导出，不把该观察直接判为开启了原文trace，也不据此声称整个磁盘完全不含参数片段。

首次Windows包装器已取得有效guest退出0与JSON，随后解码WSL stderr时因默认编码抛错，包装器退出1；保留这一区别。后续只读检查正常退出0，无重新运行宿主或导出以覆盖旧结果。

## 边界与收尾

通用export与活动详情下载是不同入口。本批不覆盖活动原文授权/撤销/TTL、敏感URL注入样本或独立导出签名验算，不提升完整A11条目通过计数。原状态未修改；新副本和导出保留在本批私有目录，私钥仍只在state/keys。没有模型、服务、监听器或计划任务创建。此证据不代表全部OpenClaw隐私旅程完成。

## 后续独立验签（已完成）

上述初批未独立验签的缺口已补齐。先固定导出原始SHA-256，读取与宿主候选同摘要的实际二进制 pubkey 输出，核对它等于文档identity公钥；读取前后状态文件摘要不变。只将已脱敏文档、公钥和签名作为验算输入，私钥没有离开WSL状态目录。

Python读取JSON，移除仅signature字段，以 `json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True)` 产生ASCII规范化字节（保留signing_schema）。附带的 verify-seal.go 仅用Go标准库 Ed25519，未调用产品 Seal/Verify/canon。实际文档验签成功；独立翻转消息字节、签名字节及替换公钥全部拒绝，命令退出0。规范化摘要与检查结果见seal-preflight.json和verification.json。

复现：将规范化消息、公钥base64、签名hex分别保存为 message.canon、public-key.base64、signature.hex，然后 `go run verify-seal.go <输入目录>`。输入是本机私有导出材料，未提交PR。此检查是独立实现的密码学复验，不冒充外部审阅者；attestation_scope仍为share_projection_only。活动原文访问/撤销/TTL及敏感URL样本仍待验收。
