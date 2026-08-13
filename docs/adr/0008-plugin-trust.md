# ADR-008：插件签名与兼容策略

- 状态：**已采纳（暂行）**
- 日期：2026-08-13

## 决策

- Connector 首版采用受限子进程 NDJSON 协议（`packages/contracts/connector-protocol.v1.md`）：不注入凭据、禁网默认、超时/输出上限/错误码契约；
- 每批 evidence 必须被本批 candidate 引用（控制面强制，孤儿证据 422）；
- 插件签名/隔离（进程/容器/Wasm）为 Phase 5 项；当前默认仅官方 Connector。

## 后果

- 正：协议简单、可测试、多语言友好。
- 负：子进程隔离弱于容器，恶意 Connector 风险在 Phase 5 前靠审计与限额。
