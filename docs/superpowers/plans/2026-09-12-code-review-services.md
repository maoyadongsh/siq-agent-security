# Code Review Services Implementation Plan

**Goal:** 为已确认的 CodeFlow 与 SonarCloud 准备可审阅、可验证的仓库接入，准确列出维护者侧启用条件。

**Architecture:** SonarCloud scope properties + 固定 Action workflow + stdlib 参数校验；离线结构测试保护凭据与事件边界。CodeFlow 使用已核实的官方服务能力，不臆造配置。

**Tech Stack:** GitHub Actions、Python stdlib、仓库已有 PyYAML、官方 SonarSource Action。

## 1. 参数与安全边界

- [x] `scripts/research/test_sonarcloud_config.py` 先验证缺失、控制字符、参数注入及 region/host 混用被拒绝；`scripts/research/sonarcloud_config.py` 仅输出经校验的非秘密连接参数。
- [x] 新增 workflow 契约检查与负向修改测试，拒绝 `pull_request_target`、fork token 路径、浮动 Action、跳过签名验证或假质量门成功。

## 2. 仓库配置

- [x] `sonar-project.properties` 使用真实源码目录；正常测试分离，构建产物与指定语料排除；不写 organization、token 或不存在的覆盖率路径。
- [x] `.github/workflows/sonarcloud.yml` 先由 `SONAR_ENABLED` 开启 main 扫描，再由 `SONAR_PR_ANALYSIS_ENABLED` 开启同仓 PR；fork/Dependabot 不上传。扫描前运行参数校验，Action 等待质量门。
- [x] `.gitignore` 排除本地 `.scannerwork/`；在既有 research CI 中运行新的离线测试。

## 3. 维护者交接

- [x] `docs/research/code-review-services.md` 记录连接变量、secret 名称、GitHub App 权限、Automatic Analysis 切换、覆盖率真实状态和 required check 启用条件。
- [x] 核实 CodeFlow 端点与官方接入说明；记录无法验证的服务状态，不冒充完成授权。
- [x] 复跑 `python3 -m unittest discover -s scripts/research -p 'test_*.py'`、`ruff check scripts/research`、研究元数据/台账及 `git diff --check`，独立审阅后交付。

## 交付状态

仓库配置与维护者指引完成；30项research单测（20项本轮、10项既有）通过，独立审阅发现的准入语料范围遗漏已修复并以真实路径做回归测试。实际服务启用仍为external_manual：未登录/授权CodeFlow，未取得SonarCloud组织、项目和token，也未执行线上扫描或修改原仓库治理设置。采用此前确认的fork PR审核方式，交给原仓库负责人审阅与配置。
