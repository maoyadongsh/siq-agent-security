# P01 真实浏览器资产发现与展示

作者侧可复核实测，尚非独立第三方认证。候选 Go 二进制仍为 fixturefix2，SHA-256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`，未修改产品。最新 `discovery-browser-002` 完成 1 条旅程、7 个观察阶段，36/36 检查通过。

## 实测方法

使用 Playwright CLI 与本机 Chromium 加载冻结二进制内嵌 UI，通过真实配对控件建立管理会话，点击分类、重新发现、额外项目目录、预览、添加目录并扫描，最后刷新页面。未替换业务 API。所有宿主配置及 Skill 均在本批独立 HOME/项目目录预埋；不会修改用户已配置宿主。配对码经一次性本地通道填入，未写入命令参数或快照。

浏览器响应采集记录真实 HTTP 状态及脱敏正文，另外采集 DOM 表格、API 原始资产投影、无障碍快照和视口截图。离线核验重建预埋清单，按资产类型与路径核对 API，再按资产 ID 链接、状态列核对 DOM，并从无障碍快照独立重建表格行进行交叉核对。

| 观察阶段 | 资产数 | 框架/角色/Skill | 关键结果 |
| --- | ---: | --- | --- |
| 框架列表 | 14 | 4 / 4 / 6 | 4 个框架归组，配置数与角色数匹配 |
| 角色列表 | 14 | 4 / 4 / 6 | 4 行角色，状态为候选 |
| Skill 列表 | 14 | 4 / 4 / 6 | 6 行 Skill，状态未准入，检查/授权为空 |
| 点击重新发现 | 14 | 4 / 4 / 6 | ID 和映射保持一致 |
| 预览额外项目 | 14 | 4 / 4 / 6 | 尚未登记，资产与已登记范围不变 |
| 添加项目并扫描 | 17 | 4 / 5 / 8 | 新增项目 profile 与 2 个 Skill |
| 刷新页面 | 17 | 4 / 5 / 8 | 展示和 API 保持一致 |

此批没有登记 API 专项中的独立手动 Skill 集合，因此预期为 17 项而非该专项的 18 项。两个批次范围不同，不混合分母。7 个阶段并非 7 个独立攻击样本。

## 安全状态解释

页面明确说明“发现配置不代表已接入保护”，顶部宿主为未接入。发现的角色为候选，Skill 为未准入，没有 Grant。部分目录扫描失败时，页面显示跳过数量和未完成扫描项入口。两个同名同内容但路径不同的 Skill 均保留独立行和链接。

角色表按既有合同省略 Skill 专属的安全检查、授权及声明工具列；不要求不存在的列填充占位符。框架 `claude_code` 和 `codex` 在该版本使用原始标识显示，这不代表宿主可用性已验证。

## 保留的首批错误 F022

`discovery-browser-001` 已采集全部 7 阶段，原评分 34/36：测评器误把两个框架的显示名和角色表的列设为另一种预期。最终写入 journal 时，沿用 P06 的 utility unknown 原因，导致已知 utility 与 unknown 原因同时出现，被统一 Schema 拒绝。

原 journal 保持未完成；没有补写通过结论。采集材料在异常退出后封存，离线核验返回 2，首次结果和 harm 均保留未知，原评分仍为 34/36。修正测评器后新建 002，36/36；没有通过修改产品迎合夹具。

| 批次 | 结果 | 封套 SHA-256 |
| --- | --- | --- |
| discovery-browser-001 | 未完成 journal，原评分 34/36，核验退出 2 | `41a90fabe30b65b26a8ba4eca736467fc5ba9cf3e41c6b253de7afd1bae6cbd3` |
| discovery-browser-002 | 36/36，退出 0 | `b51cfd358663a3cdf45ffbcffa3f92f700c603d3d8487a6b616f16d014948bc7` |

## 边界与证据

当前为 Linux aarch64、Chromium、独立配置资产的发现界面。截图为视口截图，完整行以无障碍快照和 DOM 为依据；已目视核对最新框架、角色、Skill 和登记后 4 张截图。为适配本机既有环境关闭了 Chromium 沙箱，不作浏览器/OS 隔离保证。没有执行真实宿主模型任务，不证明发现即已保护，也不替代安装更新卸载的工具效果测评。

[最新复核](discovery-browser-002-verification.json)、[首批未完成复核](discovery-browser-001-verification.json)、[观察数据](../data/discovery-browser-002/browser-observations.json)、[Skill 快照](../data/discovery-browser-002/output/playwright/skills.yaml)、[Skill 截图](../data/discovery-browser-002/output/playwright/skills.png)、[导出和资源检查](discovery-browser-export-review.json)、[复跑说明](../REPRODUCE.md)。
