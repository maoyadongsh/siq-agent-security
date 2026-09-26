# 技能位置包含关系采集与上传 v2

保留 collect_skills 的 v1 响应。Linux Directory 新增 describe.objects=skill_manifest_ancestry_v2 和 collect_skills_v2 操作，返回 enterprise-skill-collection/v2。Edge 仅在采集器显式声明新能力时调用 v2，否则继续 v1；旧 Edge 继续 v1。v2 对应 enterprise-skill-upload/v2，控制面同时接受 v1/v2，响应仍为 enterprise-skill-upload-result/v1。控制面必须先升级；旧控制面拒绝 v2 时不静默降级、重扫或重签，保留上传日志。

v2 每项 observation 增加必填 ancestor_sha256 数组：1–33 个互异小写 SHA256，第一项等于 locator_sha256，后续按实际递归链从安装目录逐级到本次获准扫描根的目录位置摘要。包含自身，不包含授权根以上的父目录；若安装目录就是根，仅一项。重叠根沿既有排序/去重，只记录实际首次读取该安装位置所用的链。隐藏目录不被递归，但可以是显式授权根；不因此扩展扫描权限。

只沿已通过 openat/O_NOFOLLOW 安全打开的递归目录链附加摘要，不读取额外文件、不从名称猜测角色。完整 SKILL.md 内容及位置摘要仍遵循 v1；失败/截断禁止上传完整结果。v1 不允许携带 ancestor_sha256，包括显式 null；v2 缺失/null/空/重复/超长/首项不一致均拒绝。Edge 校验后签名，后端严格 schema 校验；字段进入不可变 SkillUploadReceipt.signed_payload，同事务保存，可重建验签，无需改变原安装身份或覆盖旧观察。

该链是认证设备签名的历史位置包含关系，不是服务端独立测量或运行时加载证明。未来匹配必须同时校验租户、设备、角色配置证据、具体观察批次与 manifest 摘要，不得仅按同名或跨设备摘要相等合并。v1 无链保持未知；当前角色关系 API 不因此改为已关联，也不产生 effective 权限或运行时绑定。
