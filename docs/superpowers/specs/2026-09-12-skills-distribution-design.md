# SIQ Skill 分发兼容设计

日期：2026-09-12。用户已认可前一轮评估并要求落地最佳实践。

## 目标与范围

将 vercel-labs/skills 作为可选分发工具，建立固定版本、实际安装/卸载、最终文件一致性和负向测试组成的可复现验证。交付限定为研究/发布工具、CI 和文档，不改变 runtime、合同、冻结的 Skill payload、V5 源码身份或原有实验分母。

比较过的方案：直接嵌入安全核心会增加依赖与权限耦合；只补文档不能发现安装内容变动；本轮采用独立分发验证工具，提供可执行证据，同时保留现有准入与授权边界。

## 组件与数据流

1. `scripts/research/skills-upstream.json` 固定 upstream commit、npm 版本、官方 tarball URL 和摘要。
2. `scripts/research/verify_skill_distribution.py` 仅以数据形式读取源目录与安装目录，比较相对路径、SHA-256、字节数与 POSIX 可执行位。拒绝 symlink、非普通文件、读取期间检测到的变化及超过读取预算的树。不执行或导入 Skill 内容。
3. `scripts/research/skills_distribution_smoke.py` 在全新临时目录下载并先校验固定 npm 包；通过本机可信 Git 导出明确 commit 中的 SIQ Skill。Node 子进程使用显式文件读写许可、不允许子进程、关闭 telemetry、使用过滤后的环境。测试 source 为 local，分别安装到 OpenClaw/Hermes/CodeBuddy/Trae 的临时 project，比较实际内容，卸载并核对清理结果。
4. 每次报告使用独立输出路径，记录上游身份、SIQ source commit、执行环境、场景结果与证明范围；不覆盖旧证据，不记录私有主目录、token 或 Skill 正文。测试报告不创建任何 `effective` 权限。

## 边界

只向临时目录写入；不操作真实 Agent 配置，不运行 bootstrap、adapter 或候选 Skill 脚本。Node permission 的边界按实际能力描述，不能宣称网络或同 UID 的强隔离。分发内容一致性不是发布者签名验证、静态准入或 runtime enforcement 的证明。运行时授权、上游 audit、lockfile 及安装成功是不同语义。

SIQ Skill 内容保持原样，因此其中历史平台用法和二进制发布条件必须在外部接入指南中解释。三个 `secure-*` Skill 属于应用耦合场景，不能宣称为独立通用 Skill。

## 验收

- 精确文件、摘要、可执行位一致时通过；缺少、修改、额外文件、symlink、FIFO、超预算和读取期间变更均拒绝。
- 检查器报告与输出不会覆盖输入树或已有证据。
- 固定上游真实 CLI 完成四个平台的安装、内容比较和卸载；保留失败尝试并如实标注 OS/模式范围。
- 离线单测进入既有 research 检查；新增兼容 CI 使用已固定的 Actions，不自动更新上游版本或发布产物。
- 本轮不声称完成 Vercel 共享目录投递映射、外部更新接入既有撤权流程、安装前 policy hook 或 `skills use` 的准入；复用 SIQ 已有 import/skillinstall 能力，不把 Hermes 受控路径已经具备的内容逐次重验误写成尚未实现。
