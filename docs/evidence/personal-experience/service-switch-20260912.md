# M47：服务配置成对切换事务

日期 2026-09-12，当前未提交工作区；先更新规格 §3.11.11 和 local-service-switch.v1 合同。

本批是 state 层事务，不暴露未经候选发行验证的任意 unit 写入 CLI。保存已签名 source/target 与完整 unit、先日志/再 pending，复验两文件后分别替换、完成标记后移除 pending。Writer 全程持有；恢复只前滚到已签名目标。完成日志重放要求当前仍等于目标，不允许拿旧完成记录重新激活源版本。

## 验证

- Go 全量/vet、state/CLI race、156 项 Python 合同及 Ruff、四目标构建通过；gofmt 无输出。
- Go 生产事务样例规范化实例/目录并重新签名，Python 校验合同、嵌套记录和日志签名、两个 unit 摘要。
- 模拟阶段：尚未替换、仅 unit 已替换、两文件已替换但未完成；均恢复到完整目标。未知内容保留并拒绝、重叠准备拒绝、完成重试成功、完成后源字节不能被旧日志重新接受。
- 新 serve 测试：pending 存在即拒绝（包括损坏标记），不生成 signing.seed 并释放主锁。原测试误把 state.Open 创建的空 keys 目录当作生成密钥，修正为检查 signing.seed；生产行为未放宽。
- 最终 Linux 二进制隔离 init/pending/serve 负向通过，未启动实际用户服务。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `7deaf3e699e481e94682a318028b6e39abc285deb7180d4cdf04b01df41323f8` |
| siq-linux-amd64 | `4c372a006321df4e7be0045897ca83c1989730e8d09e8adf7b533366f689d9ad` |
| siq-linux-arm64 | `5079c40d5b0599d6370d09cda93ca4e1e1ee1e41510e4e6579d2125e5e078db9` |
| siq-windows-amd64 | `932a2a7da811d4d229aa35a099e2e643eabf74c61722f488fd30aecff8b1a2ac` |

本批恢复证据是文件阶段故障夹具，不是断电实测。manager 停止、发行候选再次验签、reload、启动与健康确认尚需接入上层切换命令；配置事务完成不能计为升级完成。旧任意版本不受新增 pending 代码追溯约束；不修改授权或回滚台账。完整个人与 LAN 目标 active。
