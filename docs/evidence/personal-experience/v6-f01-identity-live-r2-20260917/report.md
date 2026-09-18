# F01 沙箱实例身份绑定：真实网关复核

2026-09-17，基于 `9b8c09af742cb9df94c6d02e6f2db6ecccd68951` 的未提交 v6 集成树构建 Linux/arm64 本地候选，二进制 SHA256 为 `ceddc59c929da6ae449fdcb06f5e4f5915bf2e3ca73dad73457be421fbb194e7`。该候选把当前唯一 Ready 沙箱的 UUID 纳入 hold 签名参数；预留前重新从网关读取并比对。组件负例覆盖已批准后同名实例更换、UUID 缺失及变更，均拒绝且不启动任务；预览公开当前 UUID 供新批准构造。旧的不含 UUID 的原型批准必须重新预览、批准。

同候选 D05 驱动连接真实 OpenShell 0.0.83 网关、专属 Hermes 基础镜像沙箱和真实 SIQ daemon，第二次运行退出码 0，公开矩阵 [`d05-acceptance-matrix.json`](d05-acceptance-matrix.json) 为 **229 pass / 0 fail**，E01–E13 汇总 **9 pass / 4 partial**。组件/静态/构建回归逐项见 [`checks.json`](checks.json)；四目标构建摘要见 [`cross-builds.json`](cross-builds.json)，Linux/arm64 在 Web 重建后复编的摘要仍与实测二进制相同。E04 的过期 SEC/缺必需 Authority、E06 的加载超时/旧 CLI、E08 的远端单任务停止、E11 的持久化故障仍未由本腿完整证明。测试 Grant 的 `platform=openclaw` 为归属标签；本腿没有运行 OpenClaw 原生宿主；E12 已由真实浏览器对本候选完成预览、确认、运行及结果读回。

第一次运行在隔离 `XDG_CONFIG_HOME` 尚未登记网关元数据时，K02 的 probe 返回 `ok=false`；清理阶段 K90d 因基线摘要未建立而失败，原样保留在 [`../v6-f01-identity-live-20260917/d05-acceptance-matrix.json`](../v6-f01-identity-live-20260917/d05-acceptance-matrix.json)；随后仅在本批隔离配置中登记已有网关，未更改或重启共享网关，再运行上述第二腿。初次失败不得计作通过。第二腿后才给驱动入口补 `umask(077)`，并修正 K02 先判 `probe.ok=true` 才继续（回归 14 项通过）；因此当前脚本哈希不是运行当时的完整脚本哈希；矩阵以实际二进制摘要绑定，不能据此声称可复现的干净源码发行候选。二进制、基点和源快照的精确界限见 [`candidate.json`](candidate.json)。

本腿使用的专属沙箱 `siq-v6-f01-identity-20260917` 原 UUID 为 `aa220695-db98-4b3f-990f-6347a4cb382f`；在核对列表后按确切名称删除，之后只读列表确认已不存在。原始运行目录在忽略的 `*-private/` 下，不进入公开清单。公开矩阵经本机路径与凭据扫描；`SHA256SUMS` 覆盖本目录公开文件。共享网关及其他沙箱未操作。

剩余边界：CLI 最终仍按沙箱名称执行，UUID 读回与 `exec -n` 启动之间缺网关原子事务；网络 binary 范围未独立签入批准。这份证据证明当前实现的已知替换拒绝与真实服务正向链路，不关闭跨进程 TOCTOU、Windows/macOS、正式发行或生产后端验收。
