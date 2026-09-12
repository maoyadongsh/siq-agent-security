# M50：显式回退到原事务源配置

2026-09-12，当前 codex/personal-client-upgrade-recovery 未提交工作区，继承 M48/M49。规格 §3.11.13；复用已有签名日志和升级编排，没有新增签名对象或发行信任根。

新增 `service-rollback --transaction ID --manifest OLD --binary OLD --confirm-rollback [--recover ID]`。旧候选必须通过 v2 发行签名/兼容/平台摘要检查，规范化程序路径渲染结果必须等于原日志 SourceUnit。回退由原 TargetUnit 到原 SourceUnit 创建独立签名事务，保留原记录；失败单位无主进程时可显式回退，主 Writer 仍复验，授权与台账不回滚。

## 验证

- Go 全量/vet、CLI/state race 与四目标构建通过，gofmt 无输出。
- 单测覆盖候选不符合原源配置时不修改服务、已失败候选回退、配置保持、旧完成升级日志不能在回退后重新激活目标。
- 实际 Linux 测试两项通过（3.925s）：正常切换后显式回退；端口冲突失败→同事务恢复→显式回退。读取签名源配置与健康成功，最终清理 runtime 服务，无遗留 siq-agent-security-* 单位。
- 原生测试依旧使用同一可信构建的两个路径副本；生产 CLI 没有信任根覆盖参数。实际旧/新发行签名制品未在本批执行正向验收。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `704392da63bb7fc565be32136821cfe2808c96e6f7eec10bbe7495d20cdd84b5` |
| siq-linux-amd64 | `d248619114dd2772baf201ff91c264e9d38ab528732ff7e181da73ef3aa06874` |
| siq-linux-arm64 | `523b899e824162b6152f2a2c8dd0e9e0b81fa7075060d810bc033abdbb8b3bac` |
| siq-windows-amd64 | `51725cfd0bbf6b22771c5c87f7f1c4eebc41ae89a018f0ed257ada3aefa4a796` |

## 边界

这是用户确认的源配置回退，不是自动回退。旧程序/签名清单必须可用且处于原路径；当前不逆转半写入原事务。v1 切换日志没有原程序摘要，只绑定源配置；提供的发行清单证明待执行程序身份，不足以自动证明它是历史构建逐字节快照。后续安装交付必须补齐旧制品留存与历史身份绑定。正式跨版本与其他 OS 验收、完整个人/LAN 目标仍未完成，本批未提交/推送。
