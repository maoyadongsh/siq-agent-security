# 企业网络权限变化判定 v1（内部计划元数据）

用于 ENT-015 后续收窄/撤权预览。OpenShell 动态计划的 network_change 仅比较本次
读回的网络允许集合与将写入的网络允许集合，不代表完整策略、角色或 Skill 权限。
不修改 HTTP v1 响应结构，不提供授权、审批豁免、批量提交或生效证明。

取值为 unchanged、narrowed、expanded、mixed、unknown。仅支持当前写入器接受的
L3/L4 allow 规则；按 endpoint 与 binary_path 的笛卡尔积去重，忽略规则名称和顺序。
严格子集为 narrowed，严格超集为 expanded，两边均有独有项为 mixed。
未知字段、L7/IP/凭据改写限制、不支持的规则、超限输入均为 unknown，不剥除限制后
比较；unknown 不能进入未来的“已证明收窄”快速路径。端点、路径不猜测别名等价。

每侧最多 256 条规则，每规则最多 128 个 binary_paths，最多 4096 对展开项。
静态重建计划或没有明确 network_policies 写入段时为 unknown。
分类复用 plan_change 的同一次实际策略读回，不额外读取产生混合 revision。
其值进入预览摘要。原审批、目标归属、CAS、签名、读回和 fail-closed 检查全部保留。
