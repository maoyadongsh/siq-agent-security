# M46：签名兼容声明与升级预检

2026-09-12，当前未提交工作区。先新增规格 §3.11.10 和独立 skill-manifest.v2 合同，保留原 v1 合同/冻结发布文件。

v2 签入现有本地台账格式族、实例健康协议与 migration=none；当前仅接受精确组合。release-manifest --client-compatible 显式生成 v2。client-stage 可暂存 v1/v2；client-upgrade-check 仅接受发行根签名 v2，并再次验证当前平台唯一 pin 与候选大小/摘要，不执行候选或写状态。

## 验证

- Go 全量/vet、skillmanifest/clientrelease/CLI race、四目标构建通过，gofmt 无输出。
- Python 155 项 schema 检查及 Ruff 通过。新 Go 生产 Build/Sign 样例回灌 Python，独立 Ed25519 验签和 v1/v2 分离校验。首轮 Python 样例含中文时误用 ensure_ascii=False，与既有规范不符；修正为默认 ASCII 转义后通过，签名协议未更改。
- 正向为包内开发签名候选，覆盖 v2 预检与暂存；负向覆盖 v1 不能批准升级、未知签名状态格式/迁移方式、v1 混入新字段、v2 零大小和候选内容修改拒绝。旧清单签名回归通过。
- 最终 Linux CLI 拒绝开发发行者，未创建状态。未使用发行私钥签发正式升级候选，无真实版本切换验收声明。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `4e4e7b085f1ec5f9ca64ed81976b8d3422295c412481f59572b76256257ebd03` |
| siq-linux-amd64 | `d93253ccebaf4b512a6ca1a1ab433945bdfa65d5db710484da4c50943fbaaf25` |
| siq-linux-arm64 | `c14ece3ef8d6a42667c5f076c4a43706d44b080f25f1c51c560446a49122c8d7` |
| siq-windows-amd64 | `b093b5e7dd32854a3c6bf8bbd6f7344816961e777c99233e68cbc6e4f169f132` |

兼容声明是发行者承诺，不能代替真实版本读写兼容测试；预检成功不表示升级完成。旧任意二进制无法被新声明追溯约束，不声称已隔离旧写者。停止/切换/恢复事务与完整安装交付、跨 OS 验证仍待推进；完整目标 active。
