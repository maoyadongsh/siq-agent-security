# 企业技能身份与观察 v1

技能安装位置不是智能体角色。独立 skill_installation 用 tenant_id + edge_agent_id + locator_sha256 唯一标识；locator_sha256 是采集器规范化安装路径摘要，不是内容摘要或匿名保证。相同名称、相同内容但不同设备/位置不得合并。租户、设备必须来自服务端验证上下文，不接受上传字段替代。

skill_manifest_observation 表保存不可变清单观察：installation_id、tenant_id、manifest_sha256、parser_version、parse_status、name（可空）、allowed_tools_present、declared_tools、observed_at，以及签名上传的 batch_digest 和 batch_signature。manifest_sha256 仅标识完整 SKILL.md，不是整个技能包版本；不能由截断字节产生完整清单观察。batch_digest/signature 为来源追溯材料，不将其等同于安全检测或有效授权。

去重键为 installation_id + batch_digest：同批重试复用观察；不同批即使内容一致仍可保留观察时间与签名。安装表 tenant_id/id 联合唯一键配合观察表联合外键，防止把其他租户观察挂到此安装位置。设备所属环境及租户仍必须由入库服务在线校验，单列设备外键不足以代替授权。

解析版本为 enterprise-skill-manifest/v1；合法 parse_status 为 parsed、missing_frontmatter、unsupported、invalid_utf8。too_large 不产生完整观察。未成功解析时 name 必须为空，工具列表为空，allowed_tools_present=false；空列表不表示无权限。声明事实不能生成 effective 授权，不自动创建角色关系或运行时绑定。

旧 Evidence 批次与其候选引用门禁保持不变。独立签名上传及任务/设备范围门禁、事务审计见 enterprise-skill-upload.v1.md；确认计划首扫签发见 edge-initial-scan.v2.md，Directory 静态采集、Edge 上传恢复与企业只读清单已在源码接通。角色关联和运行绑定仍未由此实现，生产迁移/正式发行包/真实接入验收尚未完成，不将源码测试称为已上线自动盘点。迁移降级在已有技能记录时拒绝删除。
