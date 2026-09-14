# PR #48 独立只读复核

复核范围为基线 `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 到最终候选 `2f84d5af6934f3cc17354107f66beae6dc8e1b59` 的两个测试文件，以及 r1/r2 两个公开证据包。未执行被审脚本或测试，未重查 CI，未读取私密原始 stdout 或凭据，未修改源码和两个包。

最终 diff 没有需要修正的问题：`install_entry_test.go` 在 Windows 检查 wrapper 不存在、安装预览没有受控安装入口、诊断保持 needs_verification/unverified，原生登记、兼容性和运行验证仍为 unknown；非 Windows 的 wrapper 内容、0700 及先 admit 后安装顺序断言保留。`backup_restore_test.go` 在 Windows 安装后和卸载后检查两个 wrapper 均不存在，保留非 Windows 兄弟 wrapper 存在性及两侧的配置字节、原有模式和插件保留断言。使用 Lstat/IsNotExist 不会把存在的链接或任意读取错误误当不存在。没有新增 Skip，没有生产代码、合同或安全机制改动。

| 公开包 | 清单核对 | 聚焦测试顶层 | 全包顶层 | 全包子例 |
| --- | --- | --- | --- | --- |
| r1 `59d757a…` | 16 payload，209,961 bytes 全匹配 | 4 pass | 58 pass / 1 fail / 12 skip | 42 pass / 0 fail / 5 skip |
| r2 `2f84d5a…` | 16 payload，212,023 bytes 全匹配 | 5 pass | 59 pass / 0 fail / 12 skip | 42 pass / 0 fail / 5 skip |

两份 change.patch 与各自候选相对基线的实际 Git diff 一致。r1 唯一失败 `TestUninstallOfOneInstanceRestoresOnlyThatInstance` 保留，退出码为 1；r2 全包退出码为 0。跳过项与子例另列，不累计为独立顶层通过，也不以 r2 覆盖 r1。两轮聚焦测试均另有 4 个通过子例；vet 均 exit 0，没有测试事件，不计为测试用例。

公开 JSONL 的重新解析、摘要和报告数字复核见 review.json。材料明确区分 Windows 组件测试与真实 Hermes 宿主执行，未把“不生成 wrapper”宣称为新增受控安装能力或安全修复；未把测试约束、交叉构建或收尾快照扩大为原生验收或完整隔离证明。报告中尚未完成的模块与 CI 门禁属于其冻结时点，本次不重查或改写。

公开材料检查未发现本机用户名、真实个人绝对路径、SID、私钥或凭据值；已归一化的占位路径、合成数据和公开工具参数保留。此结论限于本次公开材料与规则检查，不是对未读取私密原件的独立认证，也不是独立机器重跑。审查记录和清单均为新文件，r1/r2 原包保持原字节。
