# E149 真实 OpenShell 上下文与部署预览

状态：本批实现、真实只读预览与回归完成；生产执行验收继续。承接 E148；继续真实环境接入和实际部署入口验收，不替代持久恢复后续任务。

现场预检已确认 v0.0.83 / 17671 网关在完整项目 XDG 上下文中可正常握手。E148 仅传 XDG_CONFIG_HOME 导致找不到对应客户端证书；不需要关闭 TLS、更换证书或重启网关。

Python CLI 的显式连接指纹补充实际传给子进程的 HOME、USERPROFILE、APPDATA、LOCALAPPDATA 与 XDG_CONFIG_HOME/STATE_HOME/DATA_HOME/CACHE_HOME/RUNTIME_DIR 上下文。目录配置属于 CLI 选择配置与证书的输入，改变后必须使旧缓存和部署预览失效；只返回摘要，不输出路径或读取证书私钥。指纹不等同证书内容认证，也不能证明同路径内容未被并发替换。HTTP/TLS 安全规则及 env.sh 不稳定指纹规则保持原样。

验收使用已有网关和显式目标，只执行 gateway info、status、policy get。通过隔离控制面数据库与真实 CLI 检查新预览路由，确认预览不写 Deployment/EdgeTask/Audit，目录变化使旧摘要失效。独立读取同一真实目标前后 revision/digest，确认没有变更。禁止以读回/预览成功声称策略已实际部署或行为受限。

提供可复验脚本：要求显式 CLI、endpoint、XDG 根、target、独占输出目录；只允许 loopback 测试网关；私有临时 DB/签名文件自动清理；输出仅有有界版本、摘要、计数、检查结果和候选源码哈希，不持久化原始策略、证书、环境或凭据。证据记录未改变用户网关/沙箱及未调用策略写接口。

本批不自动从任意项目脚本执行配置，不新增自动开机/容器创建/全磁盘扫描。后续真实执行可在独立验收沙箱实施，当前用户业务沙箱保持只读。

现场同时发现 v0.0.83 的 status 使用 `Version:`，现有 Python/Go 只识别 `Gateway version:`，导致握手成功仍显示 unknown。两侧增加对已通过 Server Status + 单一合法 Gateway 校验的 `Version:` 支持；旧 Gateway version 格式兼容，重复/冲突版本不选择其中之一，CLI version 与 endpoint 不作网关版本。以共享版本语料保证对等，不按识别版本提升执行能力。

真实策略读回暴露 Python 与 Go 不一致：Go 已支持 v0.0.83 endpoint 的 protocol/enforcement/rules/allowed_ips/request_body_credential_rewrite，Python 仍只认 host/port，导致真实项目目标无法预览。Python 读回需逐字段保真保留 REST/enforce、每条 allow 的 method/path、有效 CIDR 及布尔改写标记；未知字段、非 allow effect、无效限制拒绝。带扩展限制的投影仍只读，不能通过既有仅 L3/L4 的期望策略 writer（未知字段拒绝），不允许悄悄扁平化扩大权限。原完整策略与 digest 用于计划/回滚，禁止把投影作为无损替代。

本地 Go 客户端存在同类上下文指纹缺口，同步纳入相同 HOME/XDG/Windows 用户目录输入；所有 env_pair 均绑定目录，不以是否带网关名作为条件。仅改变摘要，不读取或复制凭据。已有签名历史不改写，旧预览/计划应重新检查。

完整验证与已知边界见 [E149 验收](ux-openshell-live-preview-e149-validation-20260923.md)。
