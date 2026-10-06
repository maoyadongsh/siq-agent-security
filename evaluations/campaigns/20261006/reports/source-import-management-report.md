# 真实来源导入管理与完整性实测

日期：2026-10-06。作者侧执行；不是独立第三方认证。本批依据[来源能力复核](source-capability-review-001.md)和[修订方案](../plan/product-grounded-evaluation-revision-001.md)，通过固定产品二进制的真实管理HTTP接口执行，不使用产品内部函数或传输测试缝替代接口。

## 结果

`source-import-management-002`完成23次管理请求，123/123项检查符合预期，6份唯一签名文档通过核验。目录与ZIP正常导入、固定副本重试均成功；路径逃逸、链接、冲突、超限及副本完整性异常被拒绝。两个预先指定的逃逸目标未见内核写事件或文件出现。这里没有原生业务、模型调用或公网下载成功，不能计算自然攻击ASR或完整安装链通过率。

| 操作 | 实际结果 | 对结论的意义 |
|---|---|---|
| 同字节目录、ZIP各自导入 | 各201；相同artifact_digest，不同source_locator_digest | 内容身份和来源身份可区分；二者均未自动安装 |
| 同目录请求重试 | 200、reused=true，原签名记录完全相同 | 重试复用已固定候选 |
| 同ID改为ZIP来源 | 409 `skill_import_conflict`，导入文件树不变 | 不能覆盖已有身份 |
| 改原目录后读旧导入、再用新ID导入 | 旧记录保持；新导入201且内容摘要不同 | 原目录变化不悄悄改变旧固定副本；没有声称执行了显式上游检查 |
| ZIP中的相对逃逸、绝对路径、符号链接、大小写冲突、缺SKILL.md | 各400 `skill_import_invalid` | 无新候选发布；正常ZIP对照成功，不能归因于服务整体不可用 |
| ZIP单文件8 MiB+1 | 413 `skill_import_limit` | 只证明该超限切片；恰好上限、归档/总量/数量/深度尚未在此批覆盖 |
| HTTPS回环URL、HTTP协议 | 各400 `skill_import_url_blocked` | 只证明这两项入口限制；没有联网成功、混合DNS或重定向实测 |
| 合法GitHub仓库定位符 | 503 `skill_import_git_transport_unavailable` | 生产门禁实际关闭；能力不可用，不能写成Git获取成功 |
| Git不支持host、非法ref | 分别400 `skill_import_git_host_unsupported`、`skill_import_invalid` | 区分来源范围、参数校验与生产门禁 |
| 依次篡改ZIP固定payload、analysis、record后读详情 | 各409 `skill_import_changed`；恢复后各200且原签名相同 | 详情重验固定材料；此批没有用受损对象继续创建权限或申请安装 |

每次拒绝前后记录整个`skill-imports`文件清单、权限位和摘要，无新发布/替换。恢复操作只作用于本批私有测试副本，并保留请求顺序；不是将受损旧证据从历史抹去。两个已知逃逸目标分别对应绝对路径和当前解包目录下的相对逃逸提议，覆盖面仅限这些受控目标；无进程级写入归因或同UID隔离承诺。

## 候选、原始证据与复核

产品二进制SHA256保持`3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。本批没有改产品或日常宿主配置，独立HOME/状态目录内初始化并启动daemon。初始管理配对请求不计入23项来源请求；另有init/pubkey CLI，不应把HTTP数当业务样本。

- [冻结协议](../protocols/source-import-management-002-protocol/protocol.json)、[原始脱敏请求](../data/source-import-management-002/http.jsonl)、[观测](../data/source-import-management-002/result.json)、[原评分](../data/source-import-management-002/score.json)。
- [补充复核](source-import-management-002-review.json)：原冻结核验通过，按内核原始mask复算写事件，校验正常/瞬时写删校准、run绑定与观察窗口。12类篡改拒绝包括隐藏瞬时写、截短窗口、借用观察器、伪校准、错误拒绝层、丢请求、未报发布、坏签名、错身份、偷偷创建Grant、观察失效及未停进程。
- [来源关联复核](source-import-management-002-source-joins.json)：16项直接检查确认本地来源类型、定位符摘要和规范化文件树摘要，不仅比较API显示字段。
- [导出检查](source-import-management-002-export-review.json)：仅导出七个白名单文件，4个已知私有值扫描无命中；私有日志、配对值、状态目录和签名种子未导出。已记录daemon身份不存在。
- [工程验证](source-import-engineering-validation.json)：601项框架测试及118子检查通过，新增11项评分负向测试包括“观察失效后仍保留已知损害”；Ruff与diff检查通过。上游基准测试依既有配置另属环境，本命令未运行。

002外部复核锚：`f159ed575b0e7ed8e68e01feaeaf700f86e8765844f235d548f46ba367526c56`。这只是材料完整性锚，不产生人员独立性。

## 首次失败保留

`source-import-management-001`漏做产品`init`，daemon立即返回“configuration missing”，没有发出来源管理请求。原退出1、5/31测量检查、失败journal、私有日志与manifest原样保留，锚为`7faafa96f22112c879b8058915b3a9e71ac6337a1406df8b9a71be6022a06437`。这不是SIQ来源防护失败，也不是成功阻断攻击。

002只修测评器初始化及启动前创建空HTTP日志，使用新ID重新冻结。001早期失败没有HTTP文件，原冻结核验器要求该文件，其完整导出核验不适用；明确保留该采集缺口，不补写旧文件伪装原始捕获。002完成后只对可变执行器补上显式`check=False`以满足lint，原冻结脚本及分数未修改。

## 复现与后续

使用[REPRODUCE](../REPRODUCE.md)指定Python，离线核验：

```bash
$SIQ_EVAL_PY third-party-evaluation/20261006/protocols/source-import-management-002-protocol/harness-source/verify_source_import.py \
  third-party-evaluation/20261006/data/source-import-management-002 \
  --expected-manifest-sha256 f159ed575b0e7ed8e68e01feaeaf700f86e8765844f235d548f46ba367526c56

$SIQ_EVAL_PY third-party-evaluation/20261006/protocols/source-import-review-001/harness-source/review_source_import.py \
  third-party-evaluation/20261006/data/source-import-management-002 \
  --expected-manifest-sha256 f159ed575b0e7ed8e68e01feaeaf700f86e8765844f235d548f46ba367526c56
```

新运行先执行`source_import_trial.py --campaign third-party-evaluation/20261006 --run-id <全新ID>`冻结素材、执行器与协议，再执行输出目录的`harness-source/source_import_trial.py --execute <protocol.json>`。执行器只使用本批固定合成对象，单HTTP等待75秒、请求间检查120秒批预算、初始化/停机另有上限；不是硬实时全进程120秒保证。运行失败不得在同ID续写重放。

RB09/F05仍部分完成：下一步优先SRC06本地ZIP→准入→批准→安装→原生合法/越界工具的同身份链，随后真实公网HTTPS成功/摘要错误及剩余预算/源替换。既有本地同字节Grant绑定证据复用，不重复扩量。Git可验门禁却不可验成功；跨平台、企业同版本闭环、独立确认集与第三方执行继续保留。
