# N09 glm-linux r06/r04/r07 批次逐行证据矩阵

日期：2026-09-15。两条机器可读证据腿（r04-openclaw-native-update 29 项、
r07-linux-user-journey 23 项 + 嵌套 r04 腿 29 项）均使用候选二进制
`15d688fdd4652e9efb544ece769142b60725bc0a5d2deae233062f6b910e0701`。矩阵保留 3 平台 × 3 系统 × J1–J11 的完整结构，
只把报告实际执行的检查登记为 coverage，没有任何一行标记为 `complete_acceptance`。

R06 的 Linux 产品生命周期实机证据（安装预检、后台服务、升级、回滚、未知对象保护、保留数据退出）
为 markdown 证据，无结构化 checks 列表，因此只在 note 中引用，不作为校验器覆盖声明。

Hermes/linux 本批未跑新腿（全部 unverified 并列出 required_evidence）；
WorkBuddy/linux 与 macOS/Windows 各格保持 blocked。J8（服务不可用时的原生必要调用阻断）
本批未覆盖，如实记为 unverified。

校验器通过只说明文件完整性、同一候选约束和声明的逐行 coverage 有效，不能据此宣布 N09 或个人版完成，
也不能提前启动 T01–T06。
