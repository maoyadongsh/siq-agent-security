# F06 Hermes 原生失联腿

候选 SHA256 `c8048691276590a064b5314837e35c80a2e8fba48471f1bf12c434f6b9ae9853`；固定 Hermes CLI SHA256 `4e623fce245c1fe6e70ae0edd3248b376ceaf94d560d63f5881cc7a3415ec609`。脚本 `r01-hermes-service-down-smoke.py` 退出 0，最终加强版 9/9 检查通过。先前未检查受保护读取正文泄露的一轮 9/9 结果保留于 `v6-f06-hermes-offline-20260917/`，不作为本轮最终依据。

同一隔离 Hermes profile 先运行既有 `r01-sec-hermes-native-smoke.py` 的真实 CLI/插件/工具在线正控：获准读取实际返回夹具内容，签名回执链校验通过；该阶段只停止脚本创建的 SIQ daemon。随后用同一安装的插件、Hermes CLI 与本地确定性模型发出新的原生 `read_file` 和 `write_file` 调用。先确认服务端口无监听，再核对两项工具回包被插件阻断、受保护读取正文未返回、独立文件标记不存在、离线调用前后 receipt 文件摘要逐一相同。候选及 Hermes CLI 在报告中各有独立摘要，原始证据为 [report.json](report.json)。临时 HOME、模型端口和 daemon 均由脚本拥有并在完成后关闭。

范围：写入腿的窄 Skill 在线时也没有写权限，因此它是失联零副作用检查，而失联因果以在线允许、离线拒绝的**读取**腿证明；没有网络出站副作用正控，也未覆盖 WorkBuddy 或其他操作系统。F06 的自然到期与 GUI 视觉项仍单独待验。本报告不把失联拒绝等同于宿主全局沙箱隔离。
