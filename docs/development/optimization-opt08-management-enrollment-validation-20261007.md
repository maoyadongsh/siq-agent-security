# OPT-08 D3a：原生身份的管理 HTTP 接入

日期：2026-10-07。状态：实现与本批联验通过；OPT-08 继续 implementing，总任务验收仍为 9/16（56.25%）。

## 产品变化

此前 `local-runtime-identity-create/v3` 已有签名存储与响应合同，但管理 HTTP 解析器仍拒绝创建请求，实际联验只能在 Go 测试中直接调用 Store.Create/Enroll。本批将已定义的创建 v3 接入原有管理 API，同时保留显式在线宿主门禁。

只有显式 `serve --native-host`、Engine 原生查询已经配置、NativeRuntime 的宿主桥接/身份存储/调用查询已绑定，且私有连接配置与 socket 身份有效时，管理会话才可签发原生身份。未接线或连接配置失效返回 503 `native_skill_runtime_unavailable`；畸形 JSON/策略仍返回 400。签发失败时不发布新身份。旧 v1/v2 身份创建路径保持原语义。

签发继续使用人工批准的 Agent 基线、精确 revision 和实例主体。已有未撤销根身份不能被静默替换。响应使用既有 v3 结构，只给出私有凭据文件路径与非秘密摘要；会话登记使用已有运行凭据。两种读回的 `runtime_state` 都保持 `unverified`。

**签发不是进程证明。** 创建阶段只确认显式宿主接线和配置完整性，不声称尚未启动的 Hermes 在线；实际 task_begin、Skill 来源、调用 Prepare/Bind 和裁决继续逐次核验。测试确认刚签发并登记会话的身份，未登记实际原生任务时调用 `/v1/decide` 返回 409，不能产生允许回执或执行工具。

合同见 [native-runtime-enrollment/v1](../../packages/contracts/native-runtime-enrollment.v1.md)，规格与 ADR-056 已同步。此增量替代 D2 历史材料中“创建入口尚未开放”的阶段状态；历史验证文档与证据原字节保留。

## 验证结果

| 层级 | 验证与结果 | 证明边界 |
| --- | --- | --- |
| 管理 API 正向 | 已接线服务经配对取得管理会话，创建 v3 成功；会话登记成功；响应与原有标准化 v3 样例相等 | 单元 HTTP 测试的运行核验服务为明确合成夹具 |
| 管理权限负向 | 空凭据、全局 decision 凭据、普通运行凭据、宿主发布凭据均无法创建身份 | 不扩大任何现有凭据权限 |
| 宿主接线负向 | 缺少 NativeRuntime、未绑定对象、配置变化、socket 缺失、已失效对象均拒绝，未新增身份记录 | 不将配置存在当作运行已经验证 |
| 严格合同 | 顶层额外/重复字段、null 策略、错误版本/大小写、optional 模式、额外/重复策略字段及非法制品摘要均拒绝 | 既有 JSON Schema 字段与版本不变 |
| 授权约束 | Grant revision 错配拒绝；已有有效根身份再次创建冲突；未登记任务无法执行 | 不通过新入口绕过既有批准与运行边界 |
| 实际 OpenShell | 同一真实 Hermes/Go 链路改为经 TCP HTTP 配对、创建原生身份、登记会话，18 项权限检查通过 | Skill 内容、批准操作员及初始安装仍为合成验收材料；Go 服务由显式测试启动 |

实际运行有 23 次工具尝试、18 条签名回执（14 allow、4 deny），与 D2j 相同的另外 5 次在决策前拒绝。覆盖权限交集、并发 reader/writer、重放、任务结束和三种撤权；宿主独立核对文件效果。没有因改用 HTTP 签发而绕过实际进程核验或增加允许范围。

本批验证一次性汇总：

- `go test ./...`：45 包通过，10 包无测试；server 包 56.897 秒。
- server 原生身份/在线路径定向 race 通过；`go vet ./...` 通过。
- Linux amd64/arm64、macOS arm64、Windows amd64 编译通过；不代表 Windows/macOS 原生运行验收。
- 身份创建、读回与宿主在线 Python 合同共 16 项通过。
- 全量之后仅增加实际 HTTP 响应与既有标准化样例的相等断言，单独复跑该测试通过；未重新生成历史样例、未重复全量。
- 实际 OpenShell 联验通过，Go 集成段用时 23.190 秒；独有沙箱与空网络清理成功，原网关配置及 TLS 摘要未变。

实际联验命令：

```bash
python patches/hermes/run_openshell_runtime_probe.py --online \
  --output var/optimization-20261007/opt08-openshell-enrollment-01
```

原始结果在该本地目录；可提交摘要、源码指纹、原始结果摘要及门禁记录见[结构化证据](evidence/optimization-20261007/native-runtime-enrollment.json)。凭据和服务完整状态不提交。

## 下一步

正式业务仍须有受保护的 Hermes 启动初始化与宿主生命周期管理，把真实安装、请求级身份和现有智能分析助手入口连接起来。旧插件遇到 v3 仍拒绝，不能把新身份直接塞入旧插件配置来宣称产品已启用。候选覆盖包的生产启用标记保持关闭。

日常模型任务、业务权限撤销、网络效果、升级/漂移/过期、审批重试与其余 OPT 任务继续推进；本批仅完成原生身份管理入口，不代替这些验收。
