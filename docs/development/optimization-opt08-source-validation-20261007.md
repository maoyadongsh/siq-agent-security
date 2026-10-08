# OPT-08 D2c1：原生 Skill 文件快照验证

日期：2026-10-07。范围：供可信加载器接入的文件读取与来源元数据组件。OPT-08 保持 implementing；本批未启用原生管理创建或运行路径。

## 固定业务镜像的接入调查

已从本机缓存的业务镜像 `sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02` 只读提取所需源码，未修改正在运行的业务或兄弟仓库。所建无网络临时容器已按精确 ID 移除。源码仅保留在本机忽略目录，不把上游完整源码纳入提交。

| 已核对的位置 | 对后续接入的约束 |
| --- | --- |
| `tools/skills_tool.py` 普通与插件 Skill 读取 | 两条分支均须核验实际文件；模型给出的 Skill 名称不能替代实际来源 |
| `_check_skill_view_dedup` | 当前原生缓存以 mtime/size 决定是否返回 unchanged；原生必需模式须在返回前重新核验真实字节并通知可信宿主 |
| 普通与插件内容预处理 | 可能执行模板或内联 shell；不能因主文件已读取便宣称这些副作用已获授权，后续候选须明确禁用或接入最终授权 |
| `model_tools.handle_function_call` | pre-tool hook 后仍可由执行中间件改参，因此早期钩子不是最终参数校验位置 |
| `ToolRegistry.dispatch` | 直接注册表调用能绕过早期钩子；最终门禁必须放在实际 handler 前，并传递原生调用 ID |
| `run_agent.run_conversation` | 任务开始、结束和并发工具须明确关联；不能靠线程局部变量猜测所有调用的任务归属 |

源码摘要保存在本批[证据记录](evidence/optimization-20261007/native-skill-source.json)。这些发现指导接入位置，不等于已经修改上述原生函数。

## 实现行为

[native_source.py](../../adapters/runtime/hermes-agentshield/native_source.py) 提供单任务 `SkillSourceReader`，主文件必须为规范绝对路径的 `SKILL.md`，支持文件限定在其目录树内。逐级使用目录描述符和 NOFOLLOW 打开，拒绝父目录或文件符号链接、多硬链接、FIFO、目录及超过 1 MiB 的文件；路径和源数量也有明确上限。

正文来自同一次读取的内存字节。原始摘要包含 BOM 等原字节；文本摘要使用与固定镜像 `read_text(encoding="utf-8-sig", errors="replace")` 一致的 BOM、损坏字节替换和通用换行处理。元数据不包含正文或明文路径，也不包含 Grant、allow 或“无 Skill”声明。它描述源文本，不包含后续 Hermes 添加的 banner，也不能替代完整安装包摘要。

缓存命中重新打开、读取、摘要和观察，未曾提供过的文件不能声称缓存命中。同任务已记录的主文件或支持文件发生内容漂移时拒绝。观察回调必需，正常返回只表示完成元数据处理；回调失败、错误返回值、重入、文件漂移或容量耗尽均终止 reader，不能继续使用旧缓存。fork 后的子进程不能复用父进程 reader。读前后及回调后检查文件和整条路径，关闭所有已打开描述符。

本组件只读文字，不运行模板或脚本。最终接入仍须保护只读安装和代码；竞态检查不能独立提供操作系统级隔离。发送了元数据也不等于正文最终返回成功：回调后核验可能拒绝，后续桥接不得据此单独授权工具执行。

## 验证

- 定向测试：47 项通过。覆盖最大文件、BOM/中文/损坏编码/换行、支持文件、缓存、修改内容后恢复大小与 mtime、父目录/文件替换、符号链接、硬链接、FIFO、读取中变更、短读、容量、进程派生、回调失败/重入、描述符泄漏和并发串行化。
- Hermes 适配器全套回归：230 项通过，包含原有钩子、身份、审批、运行检查、宿主通道和新增文件快照测试；上述 47 项包含在这个总数内。
- 通道集成：实际文件快照通过 D2b 的真实 Unix 凭据通道传递，首次和缓存两次均观察到元数据，正文与明文路径没有进入消息。该用例属于上面 47 项，不重复累计。
- 合同：293 项相关测试通过，包含真实 Python 文件读取器生成的 `native-skill-source/v1` 元数据、传输合同及已有 schema 回归。不是手写成功样例替代生产方校验。
- 格式：新增 Python 文件的 Ruff 通过。首次 Ruff 发现测试中的异常捕获说明和行长问题，已修复。

可复跑：

```bash
python -m pytest adapters/runtime/hermes-agentshield/tests/test_native_source.py -q
python -m pytest adapters/runtime/hermes-agentshield/tests -q
python -m pytest apps/control-api/app/tests/test_schema_contracts.py \
  apps/control-api/app/tests/test_native_host_channel_contract.py \
  apps/control-api/app/tests/test_native_skill_source_contract.py -q
```

本机使用既有 API venv（含 pytest/jsonschema）完成合同与回归；系统 Python 也独立通过上述 47 项定向测试。日志位于 `var/optimization-20261007/opt08-source-*`，不提交原始日志。

## 仍需完成

原生普通/插件/缓存加载函数尚未调用此组件，预处理器行为也尚未修改。任务生命周期、加载父链、最终参数绑定、受保护启动器、实际 OpenShell 挂载、daemon 桥接及日常双 Skill 业务验收继续属于 OPT-08 后续工作。本批没有模型调用，没有原生 Hermes 会话或 OpenShell 执行效果证据；旧插件行为与既有历史测评结论不变。
