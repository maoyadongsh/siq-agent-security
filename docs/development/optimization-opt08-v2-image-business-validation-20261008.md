# OPT-08 新镜像上的 V2 内容执行（2026-10-08）

v880 失败是因为当时运行镜像仍把 `siq-research-draft/SKILL.md` 钉在 V1 `014ac3788981848b9917115b8701ad7483bd9067a22c1939f5588d2cce0c7b12`，而获批安装声明已是 V2 `a38f8af2dfefc099c18b9876d2f8e565be77c72f5ccaf7ad1cdbd95a209759db`。来源解析要求观察到的文件哈希等于安装声明；运行时制品策略又钉住旧制品 `070e94236ba603b6e7cff70f217e3a43e15f20dd7213cb03cabade3c2cf553b2`。同一身份不能在旧镜像上执行已更换的技能字节。

本轮没有改写冻结目录 `native-final-image-20261008a`。沿用原 overlay `db2b7a522f6fe6789c3246b3ef5a4ce7ce32997747cd5153ab0c9f61ef03d7e8` 和快照 `qwen38-opt08-final-20261008a`，用未改动的公司证据技能加上 V2 研究草稿重新导出技能包 `a9f3ac75f9ddfcc78505e7a1d5b53bae0b098d73cb8f076775a53732df11c9c7`，构建新镜像 `sha256:a3be2a4a2caaafc4d909ce74645e4e568444a4a72c81d0a7312b7ec789c673e2`，制品 `c5e3e318e078e1dc28b901f7ce813e0593174e07e5f7ad8f809b312409cc9bb4`。镜像内研究技能钉为 `a38f8af2dfefc099c18b9876d2f8e565be77c72f5ccaf7ad1cdbd95a209759db`，公司技能仍为 `9f594a1bcba6cb9ce50f5c3d1960a1310444511f6a3d882c42a2b1ba847fed37`。`production_eligible` 为 false。

随后用当前二进制 `aa25999e50226f9758976a149350086294b21ab737a42aa910bdb5345d07aea5`（代码 `8c473439`）签发绑定该制品的新运行时身份，实例 `hi-fb1539d2c65f16f18a4bde38ac063cba`。研究技能 Grant `grt-si-fd97d2ac2c65f04438255b92e9f9be9b69ffa21e9fea8cac7ecba9ad20b3d59e`，安装 `sin-790526ed4f3c6d2d6180e4ef048940861de4c206eb8b1007faa4563f04ea20d5`。重启后的公开协议检查通过：父身份仍有效，已批准安装字节保持，未登记运行时不能 decide。

v881 在日常模型上 33 项检查通过。`read_file` 与 `write_file` 回执均为 allow，并绑定上述 V2 Grant；目标文件存在，内容摘要 `18a5938194b63f82f26725ca5fa870e0bf0f471b71675a99f96e52f1f68c099d`。请求摘要 `b49d669881fd06aae83abe7645cd9867780f17c2d5c0a54104533518c63bd266`。三条回执为 `rcp-51dbfd36e559035b205cd51f86276874`、`rcp-5486ec760ba91f6595e3265931536268`、`rcp-67e0fd11a5edefa1ecfb666403a83fd5`。其中 `skill_view` 回执本身是 `no_skill`；读取和写入回执携带 V2 Grant。安装文件哈希与镜像钉一致。

监管单元和 `qwen38-supervisor.env` 只在本轮临时对齐，结束后按原字节恢复：单元 `02fb70569d9b198ea4aa7958b537483dc1022cd1ad0a71ac994c02e9cedd28df`，环境 `9a3440c207a4555d32c7adbf6b0f82fb78ac27586cc22ab0580e25105dd2bba8`。模型单元保持 active，自有桥接停止后保持 inactive。

这是镜像已经包含 V2 字节时的新身份执行。它不把 v879 的旧身份、旧制品 `070e9423` 原地换成新字节后再续跑。v880 仍然说明旧镜像钉住 V1 时，V2 安装声明无法加载。资源/工具入口、四臂、平台和签名交付未收口。OPT-08/10 保持 implementing，总体仍为 11/16（68.75%）。
