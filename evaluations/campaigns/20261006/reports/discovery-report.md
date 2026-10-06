# P01 资产发现测评阶段报告

本轮为作者侧可复核实测，不是独立第三方认证。产品候选保持 fixturefix2，Go 二进制 SHA-256 为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。最新批次 `discovery-http-003`：2 条旅程、5 次扫描、4 段系统调用记录、52/52 检查通过；没有产品代码修改。

## 方法与独立预期

执行前在本批私有 HOME、项目和手动 Skill 目录预埋资产与范围外诱饵，将预期类型和位置写入 gold.json。预期清单由夹具定义生成，不从产品返回结果反推。通过真实配对、发现和资产 HTTP 接口调用冻结产品，`strace 6.8` 从 exec 启动跟踪全部子线程的文件系统调用及执行行为。正向配置文件打开作为观测控制，实际资产位置作为匹配键；默认/命名 Hermes profile 与平台配置分别计数，不能将配置资产数量解释为已安装可执行宿主数量。

离线核验不启动产品：在独立临时目录重建预埋输入，核对清单和原始文件摘要，再重算资产集、ID、状态、文件打开、执行与清理记录。凭据、完整状态目录和配对日志不导出；strace 记录路径及文件操作，不采集 read 缓冲区或 HTTP 认证内容。

| 旅程/阶段 | 预期 | 实际匹配 | 准确率 | 召回率 |
| --- | ---: | ---: | ---: | ---: |
| scope/default | 14 | 14 | 100% | 100% |
| scope/registered | 18 | 18 | 100% | 100% |
| scope/repeated | 18 | 18 | 100% | 100% |
| scope/restarted | 18 | 18 | 100% | 100% |
| invalid/default | 3 | 3 | 100% | 100% |

上述为两条固定夹具旅程中的阶段指标，重复扫描不是独立统计样本，不提供开放环境总体准确率置信区间。

## 已核对的行为

- Hermes 默认、命名和项目 profile，OpenClaw 多实例、共享/工作空间私有 Skill，以及 Codex/Claude 配置均匹配预期；重复 OpenClaw ID 去重，同名同内容而位置不同的 Skill 保持独立资产 ID。
- 相似名称目录与范围外探针不形成资产；失效/逃逸软链接、目录冒充配置、超过读取上限的配置引起可见的问题记录，扫描为 partial。未把部分扫描报告成全部成功。
- preview 前后 `discovery-roots` 文件集均为空，未创建范围记录；初始 strace 也未发现成功打开未登记的 Skill 内容。正式登记后可发现新增资产，重复扫描与进程重启后资产 ID 相同。
- 相对路径、URL 和软链接根的三个手动范围请求均为 400。资产状态只有 candidate/unadmitted，Grant 字段为空；这是 API 状态证据，尚非界面展示证据。
- 成功打开的绝对路径中没有三个预埋范围外根及逃逸软链接别名；允许范围配置打开控制存在。每段只有一次成功 exec，即测试产品本身，未执行预埋脚本；执行标记不存在，预埋输入文件摘要不变。

## 封存与校准

| 批次 | 检查 | 封套 SHA-256 |
| --- | --- | --- |
| discovery-http-001 | 52/52 | `c9aa8daefdceeef33d6461ee08629c3dbdf9562a7f5e57e781a0710279feb2bb` |
| discovery-http-002 | 52/52 | `8542b286b206d3183a0b41f658e4ca508c6aee33a22dd1b25b22e71329d87ffc` |
| discovery-http-003 | 52/52 | `f497fc573f43999da50a53313eef507e44825ffaacffcb2ac9062b0b349b1f91` |

三批分别冻结测评器版本；002 增加未知覆盖与部分观察的保守处理，003 增加软链接别名判定和 oracle 覆盖状态。全部旧材料保留。新增 11 个校准测试覆盖追踪缺失、相对路径未解析、失败/成功打开区别、软链接别名、已知违规后追踪中断、虚假 protected 状态、ID 冲突、同名资产丢失、线程交错恢复、输入删除、空拒绝记录以及重封清单篡改。

## 适用范围及后续

结果只证明本机 Linux、固定种子、已登记配置路径上的发现与受控文件打开行为。未检查所有读取机制或任意主机目录，不作 OS 沙箱或同 UID 隔离保证。未启动真实 Hermes/OpenClaw 模型运行，不证明发现的配置可用或已受保护；浏览器资产/保护状态展示已另见[浏览器专项](discovery-browser-report.md)；其他操作系统、原生安装更新卸载旅程仍需执行。

证据入口：[最新离线核验](discovery-http-003-verification.json)、[原始清单](../data/discovery-http-003/cases/scope/gold.json)、[观察](../data/discovery-http-003/cases/scope/observations.json)、[评分](../data/discovery-http-003/cases/scope/score.json)、[导出及资源检查](discovery-export-review.json)、[复跑说明](../REPRODUCE.md)。
