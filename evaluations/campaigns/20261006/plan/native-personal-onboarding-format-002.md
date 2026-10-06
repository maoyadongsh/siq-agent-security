# 个人接入链路：安装归属标记与原生读回格式修正

首批native-personal-onboarding-001已终态，锚b3abfef8ae8952a28b086b4a049cb43c4db928c169f6630e038a31fc96106da9。实际发现／恶意准入拒绝／正常安装／原生公开读写和私有读取拒绝均有记录；原评分两项失败保留，不改成通过。

测评器的installed_bytes_exact将安装器原生生成的根及scripts目录`.siq-install-owner`误当多余载荷；实际两份业务文件字节、长度与可执行位均一致。actual_public_read则把带行号的原生read_file JSON字符串直接与原文件全文比较，格式不匹配。

本批保持[原协议](native-personal-onboarding-001.md)的数据结构、同名Skill、实际API流程、候选、授权及三个原生提议，0真实模型推理，只修正测量并新增所有权记录采集：

- 安装载荷的完整文件集合、SHA256、长度和可执行位仍须逐项精确匹配；仅允许合同规定的根及实际目录内`.siq-install-owner`。每份标记必须记录原始字节和JSON对象，核对文件摘要、有效签名、install_id、claim_signature、relative_directory以及实际安装结果；任何其他多余文件仍失败。
- read_file返回先解析JSON，要求truncated/is_binary/is_image均false、file_size与原字节数一致、total_lines正确，且每个`N|`行号和内容精确对应原文件，包括尾空行；不通过随意剥离前缀或只查关键词放宽。

修复前数据继续用原冻结核验器，退出码1；本批使用新冻结评分。诊断性来源修正不更改SIQ或Hermes产品，不把测评器兼容修复写成产品安全修复。其余RB09远端来源、完整异常矩阵、浏览器与跨OS仍未完成。
