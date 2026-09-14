# Windows Hermes 安装器测试修正与模块检查

本批修正两条测试对 Windows shell wrapper 的错误预期。Windows 安装器的既有行为是不生成该 wrapper；现在测试同时检查文件缺席、能力缺口提示以及运行诊断仍为未验证。POSIX 原有内容、权限及准入顺序检查继续执行，各系统配置与多实例保留检查也继续执行。没有新增 Skip，没有修改生产代码、宿主协议或依赖。

主线基线为 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`。首次修正候选为 `59d757ae0b104f6d419a7220e64c520727d3c9a7`，最终受测代码候选为 `2f84d5af6934f3cc17354107f66beae6dc8e1b59`。后续证据提交只归档本批结果，不将运行时的候选身份替换成证据提交身份。

| Windows 本机检查 | 首次候选 r1 | 最终候选 r2 |
| --- | --- | --- |
| 聚焦测试 | 4 顶层通过；4 子例通过 | 5 顶层通过；4 子例通过 |
| 完整 adapterinstall 包 | 58 顶层通过 / 1 失败 / 12 跳过 | 59 顶层通过 / 0 失败 / 12 跳过 |
| 完整包的子例 | 42 通过 / 0 失败 / 5 跳过 | 42 通过 / 0 失败 / 5 跳过 |
| 包终态 | fail | pass |
| 包级 go vet | exit 0 | exit 0 |

顶层与子例分别统计，不能相加解释为独立测试数量。r1 唯一失败是多实例卸载测试同样要求 Windows wrapper 存在；r2 修正这一假设后完整包通过。两次原始结果均保留，未将中间失败改标为成功。两轮组件检查没有命令超时，前后源码候选和干净状态一致。

12 项顶层跳过来自符号链接能力、真实宿主 opt-in、POSIX wrapper 和进程中断恢复等已有条件；5 项子例跳过来自符号链接能力。部分断言在 Skip 前执行，也不能将整个测试列为通过。详情及逐阶段 SHA256 见 [r1 报告](r1/report.md) 和 [r2 报告](r2/report.md)。

运行使用 Windows 11 25H2 amd64、NTFS、Go 1.27.1 windows/amd64、新的私有测试目录和合成配置。白名单测试环境未传入真实宿主 opt-in 或模型凭据。工具环境控制不是 OS 网络隔离。组件测试的模拟安装不证明 Hermes 原生安装或真实工具调用。

Windows 模块级补充检查在同一干净候选 `2f84d5a…` 完成：`go vet -p=2 ./...` 返回 0；`go test -json -p=2 -parallel=1 -count=1 -timeout=90s ./...` 返回 1。45 个包终态为 **21 pass / 18 fail / 6 skip**；已取得终态的顶层测试为 577 pass / 41 fail / 34 skip，子例为 556 pass / 52 fail / 12 skip。另有 15 个已启动但没有测试终态的条目（含子例），未计入上述分母。

10 个包触发 Go 包级 90 秒超时；整个命令约 775.4 秒，未触发 900 秒外层超时。18 个失败包并不等于 18 个已确认产品缺陷：其中既有断言失败，也有预算截断，分类及剩余未知见 [模块报告](module-r3/report.md)。两条变更测试在 r3 也分别 pass（多实例卸载 5.43 秒、受控安装入口 1.82 秒）；adapterinstall 截断时未终结的是另一条测试。r2 的 adapterinstall 包已在约 208 秒的完整运行中通过；同候选在 r3 的 90 秒截断不能改写该结果，也不能据此声称整个 Windows 模块通过。其他失败没有在相同环境直接对基线逐一重放，因此本批不将其统一断言为基线已有问题或本补丁引入的回归。

根代理重新解析两个模块阶段的原始/公开事件、字节长度及 SHA256，确认终态计数、候选身份及命令超时标记一致。模块测试使用已有 MSYS2 mingw64 Python 3.10.10 和 OpenSSL 3.1.0，身份见模块摘要；没有临时 shim 或新依赖安装。固定 `localhost.localdomain` 的系统 DNS 查询属于本次允许的只读测试，不能宣称全程离线或 OS 网络隔离。Windows 计划任务相关检查限于内存 TaskDefinition/XML 和随机实例名查询，未注册、启动或删除系统任务。

附着最终代码候选 `2f84d5a…` 的 GitHub 检查为 38 success、3 skipped、0 failure；6 个工作流全部完成。实际 [agentshield 日志](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34809488471/job/103867784120) 使用 Ubuntu 24.04、Go 1.22.12，完成 `go vet ./...`、`go test ./...` 及 Linux amd64/arm64、Darwin arm64、Windows amd64 构建。实际 checkout 是 PR 合成 merge `8de603a4d61c9c7021687130e8fd7300aaf49394`，并非直接 detached head；Darwin 构建不是 macOS 原生测试。

三个跳过项是 deploy、SonarCloud Code Analysis、runtime-security-nightly。CI 的 govulncheck 仍报告 33 项 Go 标准库漏洞，按现有工作流警告后成功退出，因此不代表无漏洞。此处冻结的是代码候选检查；证据追加提交后的 CI 应从 [PR #48](https://github.com/maoyadongsh/siq-agent-security/pull/48) 当前 head 查阅。

公开子包按原字节归档，manifest 与外层索引分别核对。它们描述各自生成时点；其中“模块检查未执行”等记录不因后续执行被覆盖。私有原始产物保留在本机，公开材料使用脱敏路径与合成数据。本批没有新增真实宿主验收 pass，不关闭 Windows/P02/N09、Issue #39/#42/#43，也不更改既有冻结矩阵。宿主启动及共同核心方案另见 [PR #47](https://github.com/maoyadongsh/siq-agent-security/pull/47)。
