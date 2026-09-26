# Hermes profile 来源标识 v2

Connector 协议版本仍为 v1；profile 来源身份算法升级为 v2。候选 ID 为 hermes:v2:<sha256>，source_locator 为 hermes://profiles/v2/<sha256>，摘要输入为规范化绝对 profile 路径。显示名称仍为目录名，不用名称判定同一资产；路径不直接上传，摘要不是匿名化或硬件证明。移动目录产生新来源；配置内容变化不改变 profile 身份。

证据 ID 为 ev:hermes:v2:<sha256>，摘要输入为 profile 规范化绝对路径、NUL 分隔符及文件名。证据位置使用 profile 摘要与脱敏文件名，不泄露完整本机路径。同内容、同名文件但不同 profile 仍有独立观察。权限事实引用对应候选及其证据，不产生 effective 权限。

每个 root 的匹配项在加入扫描集合前按该 root 的非通配路径前缀校验符号链接边界；解析失败或逃逸跳过，不以第一个 root 代替全部边界。重复/词法等价位置去重。仍不读取 .env 正文、不执行被扫描文件、不扩展用户确认范围。此次不推断 Skill 归属或运行时实例。

旧版 basename 来源资产保留，不自动覆盖、删除或合并。新来源会独立入库，历史归属需后续复核；升级不声称自动完成历史迁移。

## 默认与自定义 profile 的明确范围

根可显式包含 `~/.hermes`（默认 profile）、`~/.hermes/profiles/*`（命名 profile）以及部署方指定的绝对 profile 目录；每个位置都按原路径公式保持独立身份。自定义 HERMES_HOME 必须在确认范围中解析为明确路径，不读取采集进程的 HERMES_HOME 环境变量替用户增加根。

只授权 profiles/* 时不自动包含默认 profile 或自定义根。安装计划按受控 catalog 原样投影并展示 scope；若部署方 catalog 只有 profiles/*，不能称为已覆盖默认 profile。补范围须形成新计划并重新明确确认，禁止改写既有摘要或周期意图。角色配置范围不授权递归采集其 skills，技能安装观察仍需单独确认的 Directory 范围。

本机 Linux ARM64 原生 --serve 合成夹具已验证三类明确根、窄范围不扩张与 v2 来源/布局输出；不代表正式制品、真实部署目录或其他操作系统验收。
