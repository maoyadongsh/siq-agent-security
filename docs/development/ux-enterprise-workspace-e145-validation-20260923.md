# 企业组织与角色工作台验收（E145）

日期：2026-09-23。接续 E144，推进 ENT-UX-02 的组织/角色引导。总目标保持 active，外部检查 SEC-F01–SEC-F10 继续后续排期。

## 已实现的用户旅程

企业默认首页改为“工作台”。登录仍复用原有 IAM 登录/刷新与内存访问凭证；新增页面从控制面核对当前组织、用户或服务身份、已知角色及实际访问权限。组织名称未同步时明确提示，不使用前端环境变量冒充组织名称；组织与账号标识放入折叠详情。角色提供中文职责说明，自定义角色只显示数量，不依靠角色名称猜测访问权。

工作台、侧栏和总览快捷入口按同一份权限投影显示。无权访问的深链接展示联系组织管理员的说明，不渲染对应领域页面；后端仍逐次独立校验权限。工作台与设置保持可达。刷新身份上下文失败后撤下旧组织、角色和业务入口，可显式重试；没有周期刷新打断业务表单。上下文只保存在组件内存，核对时间明确展示。

有 change:approve 而没有 policy:read 的审批人会看到缺少清单读取权限的解释和处理路径，不会被暗授读取权限。组织管理员调整授权仍在已有身份系统中完成；页面提示重新登录并核对。当前没有创建虚假的“申请权限”按钮，也不声称已实现组织切换或负责人目录。

设置页删除依赖前端开发变量推断账号/租户的展示，改为真实组织摘要；访问凭证说明修正为刷新页面后可经 IAM 会话重新获取。小屏工作入口使用单列、完整说明，移动导航可打开并按 Escape 关闭。桌面与 375px 截图已检查。

## 后端与相邻修正

新合同 `console-context/v1` 对应 `GET /api/v1/console-context`。身份来自现有 get_identity；仅按该 tenant_id 查询本控制面的 Tenant 名称，不读取兄弟仓库数据库。未同步组织名返回 null，GET 不创建组织、不写审计。不返回凭证、JWT 原文、完整权限列表或其他组织信息。已知角色最多 8 类，权限和操作为固定布尔字段；前端拒绝未知版本、缺字段、额外字段与畸形数据。

本轮没有修改角色权限表。角色说明帮助理解职责，访问布尔值才决定展示入口，API 仍按原有权限点执行。开发身份头与已验证 token 明确区分；签名测试 token 不代表生产 IAM 验收。

总览原来将所有未吊销设备计为在线，并把策略数量固定为零。现按有效设备的新鲜心跳计数，排除未报告、超时、未来时间与已吊销设备；策略按本组织实际记录计数。总览 API 与页面均要求 agent:read、env:read、policy:read，缺少权限的账号从工作台进入自己有权查看的页面。资产指标文案为“已确认及纳管资产”，不把确认当作执行保护。

## 最终验证

| 检查 | 结果与覆盖 |
| --- | --- |
| 组织工作台浏览器 | 16 项；真实 API 核对组织、默认首页、六种角色导航、审批人缺读取权解释、深链接不发领域请求、后端 403、实际候选入口、上下文 503 恢复 |
| token 与组织边界 | 同一浏览器切换到隔离签名 HS256 fixture token，实际 API 验签后展示第二组织、服务身份和自定义角色；原组织信息撤下；token/身份未写浏览器长期存储 |
| 企业接入回归 | 同一前端候选，Hermes/OpenClaw 各 28 项 E144 原生 Edge/Connector 浏览器通过，含注册、心跳、采集、候选处理、未知写结果核对和权限负向；共有检查不重复累计为不同场景 |
| API | 994 passed，新增 9 项角色访问与真实路由一致性、无身份拒绝、组织隔离/缺名不创建、GET 无写入、签名身份与角色标签独立、总览计数及权限负向 |
| 前端 | 46 文件 / 271 项通过；企业、本地和隔离开发 UI 构建通过，含 TypeScript 检查 |
| 个人端 | 最终嵌入资源候选通过 E142 结果/证据 32 项；Go 44 个测试包、vet、格式与 Linux amd64/arm64、macOS arm64、Windows amd64 构建通过 |
| 静态与迁移 | API app、新浏览器脚本 Ruff 和 git diff --check 通过；隔离 SQLite 空库 Alembic 0001→0016 通过；没有新增数据库结构 |

最终证据位于 `var/flagship/ux-e145/workspace-final`、`hermes-regression`、`openclaw-regression`、`local-results`；本地候选为 `var/flagship/ux-e145/siq-agent-security`。源文件、合同、资源树与日志摘要见 [E145 证据](../evidence/flagship-optimization-20260921/ux-enterprise-workspace-e145.json)。Edge/Connector 复用 E143 候选，未修改原生运行时或重复声称新的跨平台 Edge 验收。

## 证据边界与剩余工作

浏览器使用真实隔离 API/SQLite，角色通过开发身份头验证；另一组使用专属夹具密钥签发的 HS256 token，由实际 API 验签。没有伪造业务 API 的权限允许/拒绝；503 为明确的故障注入。它们不能替代生产 PostgreSQL、外部 IdP、RS256/JWKS、真实登录/refresh cookie、在线撤权的同链验收。

ENT-UX-02 已有组织、角色、可用读入口及无权解释，但角色分配、负责人目录、生产 IAM 联调，以及所有企业页面内写按钮的权限表达仍待完成。完整审批/部署读回工作台、业务结果产物、安装分发与真实首次使用计时仍在总任务中。导航过滤不等于后端授权实现或权限即时失效证明。

首轮测试沿用默认开发 HMAC 短密钥产生库警告，改为本测试专属长密钥后全量通过，不更改产品密钥配置。初次桌面截图发生在路由切换完成前，补充等待工作台标题后重拍；小屏入口说明原来省略，已改为完整单列。原有 Starlette/httpx 弃用提示和本地构建大包提示保留，未升级依赖掩盖。

## 复验与回滚

仓库根执行，输出目录须不存在：

```bash
python3 scripts/enterprise-experience/workspace-browser-smoke.py \
  --web var/flagship/ux-e145/dev-web \
  --out-dir var/flagship/ux-e145/recheck-workspace
python3 scripts/enterprise-experience/candidate-review-browser-smoke.py \
  --framework hermes \
  --edge var/flagship/ux-e143/edge-agent-final \
  --connector-dir var/flagship/ux-e143 \
  --web var/flagship/ux-e145/dev-web \
  --out-dir var/flagship/ux-e145/recheck-hermes
```

`dev-web` 显式启用开发身份，仅用于隔离验收；生产使用正常企业构建与生产身份配置。回滚限于 E145 页面、只读上下文与总览增量并重建资源，不恢复整个脏工作树，不改用户设备/授权/审计和 Hermes 0.21 基线。未提交、推送、发布或替换已安装应用。
