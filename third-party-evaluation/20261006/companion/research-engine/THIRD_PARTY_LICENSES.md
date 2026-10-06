# 第三方软件、模型与数据许可清单

> 本文件是 SIQ Research Engine 的工程归属和许可边界说明，便于代码评审、
> DGX Spark 部署和发布归档。它不是法律意见，也不替代任何上游许可证原文。

## 1. 许可层级

| 层级 | 权威文件或来源 | 说明 |
| --- | --- | --- |
| SIQ 自研源代码 | 根目录 [`LICENSE`](./LICENSE) | Apache License 2.0；版权主体为 `maoyadongsh`，年份为 2026。 |
| 上游软件 | 各项目的官方仓库和随附许可证 | 不因 SIQ 采用 Apache-2.0 而自动重新授权。 |
| 模型权重 | 对应模型卡、权重目录中的许可证和发布方协议 | 本仓库不包含模型权重，启动脚本只描述服务启动方式。 |
| 云端服务 | StepFun 等服务商的账户、API 和服务协议 | 服务调用不等于分发模型权重或服务端代码。 |
| 业务数据 | 数据来源方授权、隐私政策和适用法律 | 年报、招股书、会议录音、图片和客户材料不因进入运行目录而获得新许可。 |

根目录 `LICENSE` 是 SIQ 自研代码的授权文本。发布源码、容器、安装包或整机
镜像时，还必须保留各第三方组件要求的版权、许可证、NOTICE 和归属信息。

## 2. 直接集成的软件

### Qwen Hermes 0.21 候选的 MCP 运行依赖（2026-09-22）

仅独立 Qwen business snapshot 启用 Hermes 冻结 `uv.lock` 中的 MCP extra。
逐 wheel URL、版本、大小和 SHA-256 见
[`business-mcp.lock.json`](infra/openshell/sandbox/qwen38_candidate/business-mcp.lock.json)；
上游 lock 与候选基础镜像内 lock 的 SHA-256 为
`383cd8f98ec23dc3fe4cf63759ec73be5a869cc953f068b4e79ec4e8ed00287d`。
wheel 只保存在忽略的本地构建缓存；Docker 离线安装保留各包 `.dist-info/licenses`。

| 包 | 版本 | wheel 元数据许可证 |
| --- | --- | --- |
| mcp / mcp-types | 2.0.0 | MIT |
| httpx2 / httpcore2 | 2.7.0 | BSD-3-Clause |
| truststore | 0.10.4 | MIT |
| sse-starlette | 3.3.2 | BSD-3-Clause |
| opentelemetry-api | 1.39.1 | Apache-2.0 |
| importlib-metadata | 8.7.1 | Apache-2.0 |
| zipp | 3.23.0 | MIT |

[官方 SDK 2.0 发布说明](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)
记录 `FastMCP` 更名为 `MCPServer`。业务服务兼容两个入口；候选 Hermes 另应用
`0006-mcp-sdk2-readonly-annotation.patch` 适配 snake_case 注解，保留严格布尔值和冲突拒绝。
同一冻结 Hermes 0.21.0 提交 `42f0c8179e30cf6ba4cba0a8f2852e609f717773`
另应用 `0007-api-run-mcp-consent.patch`：让非 cron HTTP run 的 MCP 审批进入
该 run 已注册的回调；缺回调仍拒绝，不改变无人值守终端策略。
补丁原文件、结果文件与 patch 均记录摘要；保留 Hermes MIT 归属。
此覆盖层不修改五补丁基础镜像或其他活动公司镜像的身份。

### 2.1 NVIDIA OpenShell

- 上游项目：[NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell)
- 固定版本：`v0.0.83`
- 固定提交：`e3d26dd3ae0dee247bbc5db368545832757ac493`
- 许可证：Apache-2.0
- SIQ 用途：沙箱网关、策略编译、文件系统与网络边界、Provider 控制、BYOC
  Hermes 运行面以及本地安全补丁。
- 合规要求：保留 Apache-2.0 条款和上游归属，并在发布说明中标明 SIQ 对相关
  文件的修改。该固定上游版本没有单独的 `NOTICE` 文件。

版本、commit、补丁摘要和来源记录在
[`infra/openshell/upstream-version.json`](./infra/openshell/upstream-version.json)。

### 2.2 Hermes Agent

- 上游项目：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- 固定版本：`0.13.0`
- 固定提交：`ddb8d8fa842283ef651a6e4514f8f561f736c72e`
- 许可证：MIT
- 原始版权声明：`Copyright (c) 2025 Nous Research`
- SIQ 用途：分析助手运行时、工具循环、SSE、停止与报告编排。
- 合规要求：保留 MIT 版权和许可声明。构建脚本会把 Hermes 上游 `LICENSE`
  复制到运行时上下文；SIQ 补丁只表示修改，不改变 Hermes 的原始许可。

### 2.3 vLLM

- 上游项目：[vllm-project/vllm](https://github.com/vllm-project/vllm)
- 许可证：Apache-2.0
- SIQ 用途：Nemotron、Qwen3-VL Embedding/Reranker、MinerU 和 FunASR 的
  独立 OpenAI-compatible、pooling、score 或 ASR 服务。
- 版本边界：Nemotron 启动镜像固定 vLLM `0.20.0`；其他启动器的镜像版本由
  部署环境决定，发布时必须记录最终镜像 digest 和其中的许可证文件。

### 2.4 MinerU 软件运行时

- 上游项目：[opendatalab/MinerU](https://github.com/opendatalab/MinerU)
- 当前部署包：`mineru 3.1.2`
- 许可文本：[MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)
- 许可性质：Apache License 2.0 加附加条款。
- SIQ 用途：通过外部 MinerU API 完成 PDF、表格、图片和版面解析；MinerU
  源码和运行环境没有被 vendored 到本仓库。
- 关键附加要求：基于 MinerU 向第三方提供在线服务时，需要在产品界面或公开
  文档中显著标明使用了 MinerU；当合并口径月活超过 1 亿或月收入超过 2,000
  万美元时，继续商业使用前需要取得单独商业许可。

实际部署或重新打包时，应以所安装 MinerU 版本随附的 `LICENSE.md` 为准。

### 2.5 FunASR 软件运行时

- 上游项目：[modelscope/FunASR](https://github.com/modelscope/FunASR)
- 许可证：MIT
- SIQ 用途：语音识别、VAD、标点、说话人和会议语音处理。
- 合规要求：重新分发 FunASR 源码或运行时环境时，保留上游 MIT 版权和许可
  声明。VAD、标点和声纹模型仍需分别核对其模型许可。

### 2.6 Milvus、PyMilvus 与 PostgreSQL

- [Milvus](https://github.com/milvus-io/milvus) 与
  [PyMilvus](https://github.com/milvus-io/pymilvus)：Apache-2.0；用于向量
  存储、召回和相关数据服务。
- [PostgreSQL](https://www.postgresql.org/)：PostgreSQL License；用于财务
  事实、任务状态、证据元数据和应用持久化。
- 重新分发对应服务、二进制或容器时，保留它们各自的版权和许可证文本。

### 2.7 Python、JavaScript 与系统依赖

Python 依赖、前端依赖和传递依赖分别由以下文件声明：

- `pyproject.toml`
- `requirements.txt`
- `package.json`
- `uv.lock`、`package-lock.json` 等锁定文件

锁文件和最终构建环境中的包元数据才是具体版本许可的权威来源。发布二进制、
容器、安装包或整机镜像前，应基于实际解析环境生成 SBOM 和第三方许可报告，
不能只依赖本摘要。

## 3. 模型权重与云端模型

模型权重不包含在本仓库中。根目录 Apache-2.0 不会自动授予任何模型权重的
使用、复制或再分发权利。

| 模型或服务 | 默认标识 | 许可证或服务条款 | SIQ 使用边界 |
| --- | --- | --- | --- |
| NVIDIA Nemotron 3.5 Lightning | [`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4) | [Open Model Development Work License 1.1](https://www.openmdw.ai/license/1-1/) | 本地可选文本模型；权重单独下载，不属于 SIQ Apache-2.0 源码。 |
| NVIDIA Nemotron 3 Nano Omni | [`nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4`](https://huggingface.co/nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4) | [NVIDIA Open Model Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/) | 图片附件多模态模型；不再作为可选文本模型，权重单独下载。 |
| MinerU2.5-Pro | [`opendatalab/MinerU2.5-Pro-2604-1.2B`](https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B) | 模型卡标注 Apache-2.0 | 文档解析模型；模型许可与 MinerU 应用运行时许可分开处理。 |
| Qwen3-VL Embedding | [`Qwen/Qwen3-VL-Embedding-2B`](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) | 模型卡标注 Apache-2.0 | 多模态向量模型；用于指定的 Milvus 和记忆召回路径。 |
| Qwen3-VL Reranker | [`Qwen/Qwen3-VL-Reranker-2B`](https://huggingface.co/Qwen/Qwen3-VL-Reranker-2B) | 模型卡标注 Apache-2.0 | 候选集精排；LLM-Wiki 不使用 Embedding 或 Reranker。 |
| Fun-ASR Nano | [`FunAudioLLM/Fun-ASR-Nano-2512`](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512) | 模型卡标注 Apache-2.0 | 本地语音识别；辅助 VAD、标点和声纹模型需要单独核对。 |
| StepFun Step-3.7 Flash | 云端模型/API | StepFun 账户、API 和服务协议 | 只通过云端 Provider 调用，不分发 StepFun 权重或服务端代码。 |

模型卡和服务协议可能独立更新。每次发布或部署应记录实际下载的模型 revision、
来源 URL、许可快照、接受记录和部署清单。

## 4. 容器镜像与本地服务

仓库引用了 vLLM、Python 基础镜像、PostgreSQL、Milvus 和其他部署服务。脚本
中的镜像名称不等于将镜像内的许可证并入 SIQ 许可证。重新分发镜像或整机镜像
时，应保留所选镜像各层携带的许可证和 NOTICE，并遵守镜像仓库条款。

## 5. LLM-Wiki、数据与评测材料

LLM-Wiki 是 SIQ 自研的知识抽取、组织和逻辑跳转查询层。它不使用 Qwen3-VL
Embedding 或 Qwen3-VL Reranker 对知识进行向量化或精排，也不因底层存储引擎
的许可证而改变自身知识组织逻辑的归属。

Apache-2.0 源码许可证不自动授予年报、招股书、研究资料、客户数据、会议录音、
图片、生成式评测数据或其他业务内容的使用权。运营者必须确认数据来源授权、
隐私和录音同意要求，并遵守适用法律和来源网站条款。

仓库中的合成测试夹具，仅在确属 SIQ 原创材料且明确标记为 synthetic 时，才可
按仓库许可证理解。外部文档和媒体进入本地运行目录，不代表其被重新授权。

## 6. 发布前清单

1. 记录 Git commit、容器 image digest、锁文件、模型 revision 和许可快照。
2. 为 Python、JavaScript、容器和系统包生成与本次发布对应的 SBOM 及许可报告。
3. 在源码、二进制、容器和整机交付物中保留所需版权、许可证、归属和 NOTICE。
4. 标注对 Apache-2.0 组件的修改，并在含 Hermes 源码的运行时副本中保留 MIT 声明。
5. 将模型权重、客户数据、凭据、缓存、日志和私有运行态放在源码仓库之外。
6. 对 MinerU 附加条款、模型自定义协议和云服务条款进行单独复核。
7. 每次替换模型、镜像、依赖或上游 commit 时重新检查许可证。

本清单记录工程来源和发布边界，不构成法律意见；具体分发方案应由具备资质
的法律顾问结合实际组件版本和交付方式审查。
