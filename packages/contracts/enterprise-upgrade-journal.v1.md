# enterprise-upgrade-pending/v1

Linux 私密设备目录的升级恢复记录。记录不是授权、发行签名或升级完成回执。
本增量提供持久记录、恢复输入核验和普通任务阻断；尚无公开 apply/recover 命令。

## 文件与绑定

固定文件 `enterprise-upgrade-pending.json`，当前 UID、0600、普通单链接文件；
所有父目录须通过私密设备目录校验。记录上限 2 MiB。

* `schema_version` 固定 `enterprise-upgrade-pending/v1`。
* `intent` 原 `enterprise-upgrade-intent/v1` 完整对象；`confirmation_sha256` 沿用其规范化摘要。
* `state_baseline_sha256`：复制 State，清空 discovery_plan / discovery_plan_sha256 后，
  按 Go State 字段顺序紧凑 JSON 的 SHA-256。包含凭据的摘要绑定，但不复制凭据。
* `original_plan_bytes`：原始 State.discovery_plan 的标准 Base64，保留旧计划表达和摘要；
  必须解析成与 intent.from.plan 完全相同的计划。
* `restored_state_sha256` / `target_state_sha256`：保留其他所有 State 字段，分别替换旧/新计划、
  重算 compact plan digest，再按 State.Save 的 JSON 缩进生成状态字节后的摘要。

恢复只接受三个准确状态字节摘要之一：最初原始 state、预期新 state、重序列化后的旧 state。
相同语义但不同的其他字节也不得被当成已知中间态。计划及其摘要、身份基线、当前设备/
租户/环境/origin/架构、当前 state 和 unit 路径均须一致。unit 仅接受绑定旧/新完整字节。
恢复输入每次重新验证两份 publisher 签名暂存来源；不能仅凭 journal 自述已验签。
恢复核验不检查新安装窗口（只读检查必须能诊断过期事务）；后续向新版本切换须再次检查窗口。

## 持久化与并发

调用者在整个事务持有设备任务锁。创建前重新执行只读 review 并核对显式确认摘要；
凭据轮转日志、周期确认/确认回执或周期退出日志存在时，拒绝新升级且保留文件。
已确认周期同样绑定旧安装计划，须通过现有在线撤销及显式归档流程退出，之后才可升级。
历史 registration-pending 是现有注册流程保留的历史，不等同尚未注册；当前完整身份仍须校验。

pending 用排他创建，文件 fsync、父目录 fsync、严格读回完成后才可进行任何配置修改。
写入失败保留不完整 pending，禁止自动删除/覆盖；任何 pending（含损坏、链接、目录）阻止
普通任务锁持有者启动任务。内部原始锁只供显式恢复入口使用，不增加公共绕过参数。
serve/tasks 先取得锁再读取状态，避免升级完成后仍使用锁前读取的旧计划。

## 边界与后续阶段

本增量不修改 state、unit、周期授权或执行台账，不调用 systemctl、不运行 connector。
实际 stopped-service 核验、配置切换、故障恢复、完成归档及公开 CLI 后续实现。
原有未包含 pending 阻断逻辑的旧 Edge 二进制不因生成此记录自动获得保护；正式升级来源
必须包含该能力，不能把早期候选包的测试拼接成完整断电恢复验收。同 UID/root 管理员仍是信任边界。
