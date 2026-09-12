# CodeFlow 与 SonarCloud 审查接入

用户已明确服务为 `https://app.getcodeflow.com/` 和 SonarCloud Code Analysis。本轮准备仓库端静态审查配置，不改产品 runtime、合同或冻结证据；独立于 Skills 分发 PR #29，基线为 `1e20635843c0966e24d73d149e3d7bcd080f89c4`。

## 方案

SonarCloud 使用官方固定版本的 GitHub Action，以一个多语言项目分析 Go、Python、JS/TS 源码。选择 CI 分析而非 Automatic Analysis，以便明确排除生成产物和研究语料、将来接收真实覆盖率。服务端启用需维护者关闭 Automatic Analysis 并绑定项目。

默认不开启上传。维护者填写 organization/project key、可选区域及 `SONAR_TOKEN` 后开启主分支基线分析；同仓 PR 另有开关，在完成主分支基线及计划能力核验后启用。fork PR、Dependabot、非 main 手动触发不读取 Sonar token，不使用 `pull_request_target` 或特权 `workflow_run` 执行 PR 内容。

所有 Action 固定完整 commit，checkout 不持久化凭据。参数校验拒绝空字段、控制字符和额外参数；Cloud 区域与 Server URL 分开。只有扫描 Action 获取 token，保留 Scanner 签名验证，等待真实质量门；失败与超时不能显示为扫描通过。

正常测试文件单独归 tests。排除构建输出、vendor、复制的嵌入适配器以及明确的恶意语料；不以排除全部测试或伪造覆盖率改善指标。未生成覆盖率报告时不配置虚假报告路径。

CodeFlow 通过其官方服务接入。先核验可达性、GitHub 授权方式和语言覆盖；没有已验证的官方配置格式时不创建猜测性的 YAML，也不替换成 CodeQL。账号登录、组织授权和保护规则由原仓库维护者执行；当前 GitHub 账号对原仓库仅有 READ 权限。

## 验收

- 离线参数测试和 workflow 安全契约测试覆盖配置缺失、参数注入、fork 凭据边界、Action pin、真实质量门和禁用状态。
- 既有 research 单测、元数据、台账及 Actions 检查通过；无产品代码改动。
- 文档区分“仓库配置完成”和“线上服务启用”。首次真实 main/PR 分析及 CodeFlow 服务确认前，不声明审查生效，不设置 required check。
