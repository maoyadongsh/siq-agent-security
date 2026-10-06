# 个人接入、自检及运行审计的真实浏览器测评

日期：2026-10-06。作者侧真实执行及离线复核，不是独立第三方认证。

**修正测评器的导航和展示合同假设后，完整浏览器批次003的36/36项检查符合预期。** 实际经过浏览器接入、真实Hermes自检、活动追溯、配置变化失效、取消及卸载。原两次中断保留为未知，不以003覆盖。补充核验将页面回执摘要与完整签名链关联，九类离线篡改全部拒绝。没有修改SIQ或Hermes代码。

## 从项目功能出发测什么

[项目功能理解](project-function-understanding.md)已梳理40项能力和六条产品链；本批补齐RB09个人接入的一项浏览器变体，并为RB11活动审计提供局部证据。不是新增攻击成功率榜单，也不把发现、接入、自检通过或任务完成视作同一状态。

所测固定候选为 `5470ab3780f2-nativefixturefix1`，SIQ二进制SHA256为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。宿主使用本机原Hermes CLI，在独立测评profile启动；不是生产业务会话。三个协议均固定相同候选及宿主身份，新增测评器各自冻结。真实内嵌UI由Playwright CLI操作，无API响应mock；产品自检启动真实Hermes并使用受控协议服务，真实模型推理为0次。

| 产品步骤 | 实际观察 | 能支持的判断 |
| --- | --- | --- |
| 接入与预览 | UI发起实际安装；未生成业务Grant；preview也未生成Grant | 接入或查看预览不自动授权业务 |
| 开始并后台运行 | 首次运行中关闭窗口，刷新后重新打开同一check | 可恢复查看，不因刷新重复启动 |
| 自检通过 | 同实例新会话，读allow—写deny—读allow；五条相关签名回执 | 产品自检按所定义的合成探针工作 |
| 活动追溯 | 从自检跳入同一活动，五条摘要与原始签名回执的14字段有序投影一致 | 不是借用另一任务的成功记录 |
| 结果呈现 | API为unknown/not_required；UI为“未设置结果核验”，说明调用记录不能证明任务完成 | 自检通过没有冒充业务结果verified |
| 列表与小屏 | 返回后task/agent/session筛选一致，刷新保持范围；390px视口未横向溢出 | 本页筛选与此视口可用；不代表全部移动端验收 |
| 配置变化 | 加入配置注释后旧check变invalidated，启动按钮不可用 | 当前快照不能借用旧通过状态 |
| 恢复配置 | 原check仍invalidated | 恢复字节不会复活失效结果 |
| 新自检取消 | 新check由UI取消；API与UI均cancelled，cleanup complete；两份临时Grant均revoked，材料目录为空 | 取消后的权限与材料已清理；不能倒推取消前无动作 |
| 卸载 | UI移除本实例插件，重新显示接入入口；其他profile保留 | 本实例接入可撤销，没有移除其他profile |

003中实际导出10条唯一签名回执：首次通过的5条，以及另一check关联的5条；取消结果自身receipt_ids为空。取消前已经发生的调用不能撤回，本批没有要求或证明“取消前零执行”。自检临时探针未另设独立系统调用效果观察器，因此harm仍为unknown；不拿产品的passed或deny证明实际损害一定未发生。前序[同实例API自检](native-personal-runtime-check-report.md)及[原生业务效果](native-effects-report.md)是不同范围的证据，必须分别引用。

## 三次执行与核验问题完整保留

| 批次 | 完整旅程结果 | 已满足检查 | 命名阶段 | 捕获浏览器HTTP响应 | 签名回执 / 自检修订 |
| --- | --- | --- | --- | --- | --- |
| personal-runtime-browser-001 | 未完成／unknown | 3/36 | 0 | 22 | 0 / 0 |
| personal-runtime-browser-navigation-002 | 未完成／unknown | 16/36 | 3 | 80 | 5 / 6 |
| personal-runtime-browser-presentation-003 | 完整／符合预期 | 36/36 | 11 | 151 | 10 / 14 |

001未展开“管理已发现实例的接入”，测评器找不到安装按钮。002修正导航后已完成真实自检，但等待旧文案“效果仍未知”；当前合同准确展示unknown/not_required对应的“未设置结果核验”。003同时核对准确API状态、理由与三句展示文案，执行完整旅程。三次均为同一个既有任务块的测评器迭代，不是三个独立攻击样本，不增加S4确认任务数。

原冻结002离线核验器还在未采集activity_detail时抛KeyError，使用[独立补充工具](../engineering-evidence/personal-runtime-browser-partial-review-tools-001/review-manifest.json)验证已有材料，未知保持未知。003冻结核验器则错误地比较摘要与完整回执全文，原失败见[日志](personal-runtime-browser-presentation-003-initial-verifier.txt)。[执行后复核说明](../plan/personal-runtime-browser-postrun-review-001.md)明确这不是运行前预注册。

003补充核验以固定候选JSON Schema与Go摘要构造器为依据，精确核对14字段投影；对内存副本继续运行原核验器的签名、历史、最新修订、任务绑定、启动唯一性等检查。原协议与数据不改。[补充核验结果](personal-runtime-browser-presentation-003-verification.json)与[九类负例](personal-runtime-browser-presentation-003-negatives.json)分别保留。负例为签名修订、借用任务/回执、错误unknown理由、虚报verified、恢复旧pass、重复启动、篡改摘要动作及次序，均不计入真实攻击数量。

## 证据、可复核性与资源

| 批次 | manifest外部摘要锚 | 导出文件 |
| --- | --- | --- |
| 001 | `d5e7dcca197b847fcacdcd65f1a45496bc25c4470f76050e13ba491645b227be` | 23 |
| 002 | `36d17ac0a9c36b6fce69d6798d47c6d0654ddf50ac93c1fa1fd7cb7ee5dfa473` | 120 |
| 003 | `fcc3e4ba2e2b191d8b63db4aa957a8a6c697127b46452b4bd1da6e47017e94b2` | 166 |

数据位于 `data/<run_id>/`，含完整性清单、浏览器操作输出、DOM快照、命名截图、脱敏响应、签名历史与清理结果。白名单导出筛查分别24、27、27种已知私有值形式，匹配0；浏览器会话值已脱敏，浏览器profile、隐藏原始快照和宿主私有目录不导出。仅在本机保存，未发布。

人工查看了002自检通过截图及003活动详情、小屏、失效、取消、卸载截图；小屏截图仅覆盖首屏，筛选范围和宽度另有DOM检查，不声称逐像素审查所有页面。Chromium在本机使用关闭sandbox的测试启动参数，不据此主张OS隔离。

三个批次daemon均已退出，所属进程组无残留；浏览器及一次性配对输入服务均关闭。进一步身份复查见[资源索引](../inventory/personal-runtime-browser-integration-001.json)。未新建容器。

测评框架回归 **573项与118个子检查通过**，七个本批Python文件Ruff通过。最初直接收集全目录因独立上游AgentDojo测试环境缺依赖而退出2，原日志002保留；正确框架命令显式排除upstream_tests，修正未来核验器后的最终结果日志004不包含上游测试成绩。精确命令见[复现说明](../REPRODUCE.md)。

## 尚未关闭的范围

RB09/Q4仍部分完成。已验证本候选下正常自检、页面追溯、配置注释漂移及一次实际取消。超时、取消不同执行时点、CLI/适配器制品或权限变化、完整来源异常、其他真实宿主与OS仍须单独冻结验证；不能从本批外推。业务效果与自然模型攻击收益、企业治理、第三方独立执行也不能由浏览器36项通过替代。
