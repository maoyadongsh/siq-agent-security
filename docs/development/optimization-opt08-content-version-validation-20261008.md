# OPT-08：Hermes 原生 Skill 内容版本升级

日期：2026-10-08。安全提交 `8c473439e33b`。状态：本路径通过，OPT-08 与 OPT-10 仍在实施。

## 1. 范围

同一内容的授权换代不能代替内容版本升级。本批在当前安全二进制上跑既有 Hermes 原生更新流程：公开 `hermes chat --oneshot`、真实插件钩子和文件工具、隔离 profile、本地确定性模型。没有调用日常模型，没有占用或重启 8005 模型桥，也没有改业务仓库。

这不是 DGX 日常业务入口上 `siq-research-draft` 的内容版本矩阵，不能并入 v870/v871 或 v872。

## 2. 结果

当前二进制 SHA-256：`aa25999e50226f9758976a149350086294b21ab737a42aa910bdb5345d07aea5`。16 项检查通过。

| 观察 | 结果 |
| --- | --- |
| V1 / V2 内容哈希 | `32015f33555a755007638ecbb077644fcf633d7a4e5db148feb1f2231ce65652` / `19faafa0cdc6bf1e66ea408b0f4a45a77c41d782798c938a68a5313a14b95c70` |
| 确认前取消 | 不改 V1 文件和授权 |
| 明确更新 | 替换字节并撤销 V1 Grant |
| 更新后的 V1 决策凭据 | `scoped_decision_credential_required`，无新回执、无文件效果 |
| V2 | 新安装、新身份、新 SEC；原生提示加载新内容，实际读取执行 |
| 回执 | 4 条，链验签通过 |
| 收尾 | 撤销 V2 并删除目标；其他 profile 配置保持 |

公开记录：[native-content-version-r04.json](evidence/optimization-20261007/native-content-version-r04.json)。

## 3. 仍未收口

日常业务入口的内容版本、资源与工具入口、最终同候选矩阵、四臂、平台和签名交付都还没有做。模型桥端口当时已被其他监听占用，本批没有去抢。OPT-08、OPT-10 保持 implementing，总体仍为 11/16。
