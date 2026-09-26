# OpenClaw 默认角色发现 v1

依据 [OpenClaw 官方单智能体模式说明](https://docs.openclaw.ai/concepts/multi-agent)，无显式角色配置时默认角色标识为 main。采集器仅在已授权根的 openclaw.json 成功解析为 JSON 对象、agents.list 和 agents.entries 均缺省时，生成 main 配置候选；不会在配置缺失、损坏或读取失败时生成。

默认候选 attributes.role_identity_basis=config_default，显式 list/entries 候选为 explicit_config；均非运行实例。默认角色继承显式 agents.defaults.workspace/model/skills，不从扫描进程环境、目录名或约定路径构造权限。未配置的工作区不生成文件系统权限。技能仍为范围声明，不证明安装、加载或授权生效。

候选位置身份沿用 enterprise-openclaw-identity/v2 的根目录+角色 ID；将默认 main 改为显式 main 不制造第二身份。完整配置摘要变化产生新观察证据。明确空 roster 保持空结果；null roster、null agents/defaults、非对象根、重复 JSON 键、深度超过 64 或任意 $include 均拒绝，不能通过解析歧义或未读取的外部配置推导默认角色。

新增属性不改变既有批次协议，旧消费者可忽略，但不能用其证明实际运行。JSON5 静态转换扩展见 enterprise-openclaw-json5/v1；外部 include 的受控解析和完整默认值兼容性仍待实现。仅静态解析，无配置执行或智能体启动。

已识别结构字段必须匹配合同拼写，包括 agents/list/entries/defaults、角色字段以及
agentDir。拒绝 Go JSON 默认允许的大小写折叠别名，例如 Agents、List、WORKSPACE，
避免精确键存在性检查与结构解码不一致，覆盖显式 roster 或制造默认角色/权限。
JSON5 转义键先解码再检查。此规则只作用于已识别结构字段；entries 下的动态角色 ID
保留大小写差异，未知扩展字段与不透明 model 对象不按角色结构递归套用字段规则。
