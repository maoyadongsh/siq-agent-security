# CodeFlow 与 SonarCloud 代码审查

本轮接入的服务是 [CodeFlow](https://app.getcodeflow.com/) 和 SonarCloud Code Analysis，不是 GitHub CodeQL。仓库端已提供可选 SonarCloud CI 配置；实际账号授权、项目绑定及首次扫描尚未完成。CodeFlow 需仓库管理员从服务界面连接，当前没有本仓库的真实分析结果。

现有 gitleaks、Ruff、Go vet/test、依赖审计和安全回归继续运行。静态分析结果用于审阅，不能产生产品的 effective 权限，也不能替代安全不变量测试或人工审核。

## SonarCloud 的维护者启用步骤

1. 在 SonarCloud 中导入或选择本仓库，记录界面给出的 organization key、project key 与区域。绑定正确的 GitHub 仓库和 PR 反馈权限；不要把 GitHub 用户名自动当作 organization key。
2. 使用本 PR 的 CI 分析前，在 Project → Administration → Analysis Method 关闭 Automatic Analysis。两种分析同时启用会使 CI 分析失败；删除配置文件不会代替服务端切换。
3. 在原仓库 Settings → Secrets and variables → Actions 配置下表。当前操作账号 `sunbos` 对 `maoyadongsh/siq-agent-security` 仅有 READ 权限，不能替维护者配置这些设置。
4. 合并配置后先开启 main 分析，通过主分支 push 或在 main 手动运行 `sonarcloud` 工作流建立基线。确认结果确实包含预期源码和测试分类。
5. 核验组织计划的 PR 分析能力，再开启同仓 PR 分析并实际验证一个 PR。fork 与 Dependabot 仍不上传；当前 PR #29 就属于 fork PR，不能声称这套凭据方案已为它提供 Sonar 分析。
6. 取得真实扫描结果、核对现有告警和质量门配置后，再决定合并门禁。不要把 setup notice 或跳过的扫描 job 设为 required check；当前方案也不适合作为要求所有 fork PR 必须通过的统一门禁。

| 配置 | 类型 | 内容 |
| --- | --- | --- |
| `SONAR_ORGANIZATION` | Actions variable | SonarCloud 实际组织 key |
| `SONAR_PROJECT_KEY` | Actions variable | SonarCloud 实际项目 key |
| `SONAR_REGION` | Actions variable，可省略 | EU 留空或 `eu`；US 为 `us` |
| `SONAR_TOKEN` | Actions secret | 有权分析该项目的 token，不能写入配置文件、日志或 PR |
| `SONAR_ENABLED` | Actions variable | 首次启用 main 分析时设为 `true`，默认未启用 |
| `SONAR_PR_ANALYSIS_ENABLED` | Actions variable | 完成基线和计划核验后设为 `true`，默认不分析同仓 PR |

这份配置专用于 Cloud：`SONAR_HOST_URL` 应留空。参数脚本拒绝非空 Server URL、空项目标识、控制字符和注入额外参数的值。Cloud US 使用 `SONAR_REGION=us`，不通过覆盖 host URL 模拟区域。

工作流限制为原仓库 main，以及明确启用后的同仓 main 目标 PR。Action 固定为 [v8.2.1 的 commit](https://github.com/SonarSource/sonarqube-scan-action/tree/22918119ff8e1ca75a623e15c8296b6ea4fbe28f)，保留 Scanner 签名校验；checkout 不保存 Git 凭据。只有扫描步骤获取 `SONAR_TOKEN`，该 job 不运行 npm lifecycle、测试或被扫描 Skill 脚本。没有 `pull_request_target`、特权 `workflow_run` 或自动合并路径。

扫描设置 `sonar.qualitygate.wait=true`，最多等待质量门 300 秒。扫描失败、服务处理超时或质量门失败都会使分析任务失败，不使用 `continue-on-error` 将其伪装成成功。未启用时的 setup status 明确说明没有扫描，不代表质量门通过。

## 分析范围与覆盖率

[sonar-project.properties](../../sonar-project.properties) 把 `apps`、`edge`、`connectors`、`adapters`、`scripts`、`packages` 作为一个多语言项目；正常 Go/Python/JS/TS 测试归入 tests。嵌入的 UI 构建产物、适配器复制件、依赖缓存和指定测试语料单独排除。`skills`、`benchmarks` 和文档证据不在本轮源码范围内，恶意语料继续由原有安全回归负责。

本轮**没有接入覆盖率报告**。当前文件也没有虚构报告路径或通过排除所有测试美化指标。SonarCloud 不自行产生覆盖率：后续需测试 job 实际生成 Go coverprofile、Python Cobertura XML、JS/TS LCOV，再分别配置 `sonar.go.coverage.reportPaths`、`sonar.python.coverage.reportPaths`、`sonar.javascript.lcov.reportPaths`。生成报告的测试阶段不持有 Sonar token。

若项目质量门要求新代码覆盖率，维护者应先补齐真实报告再采用该要求；首次质量门失败不能解释为 CI 配置已经证明代码不安全，也不能删掉检查来伪称通过。

## CodeFlow 的维护者接入步骤

1. 从 [CodeFlow 应用](https://app.getcodeflow.com/) 选择 GitHub 登录，核对实际授权页面显示的发布者和权限。
2. 由原仓库 admin/owner 选择 `maoyadongsh/siq-agent-security`。官方 [Getting Started](https://www.getcodeflow.com/getting-started.html) 说明首次注册 webhook 需要 admin；如果当前界面要求安装 GitHub App，以界面中的真实 App 和仓库授权为准，不猜测 App slug 或安装 URL。
3. 注册仓库并执行第一次 main 分析。之后用一个 PR 核验新增/解决问题对比、实际分析文件、耗时和反馈位置，参照官方 [PR 分析说明](https://www.getcodeflow.com/pull-requests.html)。
4. 首次实际运行后记录检查名称和覆盖范围，再决定是否启用 required check；本轮不能把用户提供的 `CodeFlow analyze results` 当作已验证的 GitHub check context。

2026-09-12 只读检查中，应用 HTML 和公开 JS 可获取；这仅证明公开入口可达，不证明登录或分析后端已完成验证。公开文档仍包含旧版工具示例。官方[语言列表](https://www.getcodeflow.com/supported-languages.html)列出 Python、JavaScript/TypeScript 等，但未列出 Go；现代 Python/TS 和 monorepo 配置发现必须通过首次扫描验证。

官方仅查到 linter 原生配置，例如 [Pylint](https://www.getcodeflow.com/pylint-configuration.html) 和 [ESLint](https://www.getcodeflow.com/eslint-configuration.html)；没有查到可采用的官方 `.codeflow.yml` 或 GitHub Action。为此本轮不创建同名占位文件，不将旧 TSLint/Pylint 示例强行替换现有工具。CodeFlow 的[安全说明](https://www.getcodeflow.com/security.html)说明服务会克隆仓库并保存展示报告需要的代码片段，授权应由负责人完成。

## 验证与实际状态

离线验证命令：

```bash
python3 -m unittest discover -s scripts/research -p 'test_*.py'
ruff check scripts/research
python3 scripts/research/check_metadata.py
python3 scripts/check_research_task_ledger.py
python3 scripts/check_ci_action_pins.py
git diff --check
```

参数测试覆盖 EU/US、缺失配置、控制字符与参数注入、空/非空 host、token 不被读取和输出失败。workflow 契约测试拒绝移除 fork/main/Dependabot 条件、扩散 token、浮动 Action、跳过签名校验和放宽质量门。

2026-09-12 本地验证：30 项 research 单测通过（20 项本轮参数/工作流测试、10 项既有测试），ruff、元数据、任务台账与既有 Actions pin 检查通过；使用模拟的非秘密组织/项目标识验证了 GitHub 输出文件格式，没有上传分析数据。

服务端状态仍为 `external_manual`：尚无 SonarCloud organization/project key 或可用 token；未授权 CodeFlow，未修改原仓库 settings/secrets/保护规则；未执行任何真实 SonarCloud/CodeFlow 扫描。不能将离线配置测试算作线上 Code Analysis 通过。

官方依据：[Sonar Scan Action](https://github.com/SonarSource/sonarqube-scan-action)、[Cloud 分析参数](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/analysis-parameters/parameters-not-settable-in-ui)、[Automatic Analysis](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis)、[覆盖率参数](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/test-coverage-parameters)。
