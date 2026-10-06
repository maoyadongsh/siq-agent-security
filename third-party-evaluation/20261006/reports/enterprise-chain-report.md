# 企业原生发现、审批部署与真实执行效果测评

日期：2026-10-06。作者侧受控实测，不是独立第三方认证。

`enterprise-chain-004`已在同一候选版本上完成原生Edge/Connector发现→候选资产→实例与后端绑定→策略变更→独立审核者批准→目标授权→部署读回→真实请求拒绝→回滚恢复。97项评测器显式HTTP请求（含管理与合成Edge协议调用）、144/144项检查通过。接收端实际观察到“请求到达→收紧后未到达→回滚后再次到达”；三阶段健康控制均成功。

这证明本配置下**SIQ治理流程驱动OpenShell后端产生了可观察的执行限制，并可恢复合法请求**。它不是纯SIQ本地运行时、任意宿主或自然提示注入防护率的结论。所执行的是sandbox内受控curl网络任务，没有在该sandbox运行Hermes模型任务。

## 同一候选与真实链路

Control API、原生Edge和Hermes Connector均来自`5470ab3780f2-governancefix1`隔离候选，源文件及本次构建摘要已冻结，未将较早fixturefix2适配器探针混入。产品代码未因本轮而改变。原生二进制摘要见[构建清单](../inventory/enterprise-native-build-001.json)。OpenShell使用已校验的0.0.104工具链；数据库、测试RS256/JWKS发行器、mTLS网关、sandbox、接收容器和网络均为本批独立资源。

1. 原生Edge通过stdin获得本批注册code，私有状态保持600。它领取生产API签发的定向扫描任务，经原生Hermes Connector扫描独立HOME内唯一config.yaml，上传1个候选和1份证据，任务状态为`delivered`。CLI并非模拟；config未被修改，未调用模型。
2. 从真实资产API和独立PostgreSQL关联设备、环境、任务、候选、evidence_ids、collector与原始文件摘要；服务端接受了原生签名材料。本次不将数据库保存的签名字段存在冒充外部独立签名复核。此前合成Edge客户端的负向协议测试同时运行，但其fixture-a没有被用于本次后端部署目标。
3. 对原生发现的`enterprise-native-fixture`创建实例、OpenShell binding、网络策略与变更；由不同reviewer批准。尚无operator target authority时，部署返回409 `deployment_target_authority_unverified`且无副作用；明确分配本批目标后才进行preview/submit。
4. 实验基线允许`/usr/bin/curl`访问本批私有网络中的`effect-sink:8080`。SIQ部署的收紧策略仅允许`example.test:443`，撤去原接收端访问。后端配置、数据库effective记录和receipt核对的是各自真实身份；desired-policy版本没有混同为OpenShell实际版本。
5. SIQ回滚恢复原网络策略。随后继续验证旧receipt与新状态不匹配、preview后真实策略漂移阻止旧preview提交，以及网关停止后返回unreachable、客户端自报verified不能提升状态。

接收端不对宿主开放端口，只接收合成随机nonce；目标授权覆盖本批明确的asset/instance/environment/endpoint指纹，没有影响本机原有网关或sandbox。

## 可归因的实际效果

| 阶段 | OpenShell读回版本 | sandbox真实请求 | 接收端业务nonce | 接收端健康控制 |
|---|---|---|---|---|
| SIQ部署前基线 | 2 | exit 0，返回正确nonce路径 | 1次 | 成功 |
| SIQ审批并部署收紧策略后 | 3 | curl exit 22，HTTP 403 | 0次 | 成功 |
| SIQ回滚后 | 4 | exit 0，返回正确nonce路径 | 1次 | 成功 |

三次均为同一sandbox、同一接收容器，使用不同不可预测nonce。独立接收日志、真实CLI原始stdout/stderr、命令结束状态及顺序，与每阶段的配置读回逐一关联。负向阶段不能用“接收端宕机”解释，正常和恢复阶段同时验证调用成功、接收次数及返回身份。回滚恢复的是策略内容，不要求版本号倒退。

这些是同一受控任务的3个阶段，不是3个独立攻击样本；本批没有B0/B1统计比较、真实模型攻击机会或新的S4确认集任务。没有抓取全部网络包，结论限于指定接收端和业务请求。

## 所有尝试与发现

| 尝试 | 实际进展 | 失败/修订及处理 |
|---|---|---|
| 网络环境预检001 | 观察到到达、403无到达、恢复到达；原检查2/4 | 正常CLI输出为空。接收端随后补充Content-Length，新批仍要求正常返回内容正确；原预检未改分 |
| 企业001 | 两次迁移与head检查完成，0项显式HTTP | umask077产生600脚本，移除全部capabilities的容器root无权读宿主文件；改为本机UID/GID，未放宽文件权限 |
| 企业002 | 77项显式HTTP；原生注册成功 | 工作区775祖先导致Edge拒读状态，tasks失败、扫描pending。保留安全拒绝；改用0700临时工作根，不修改工作区或产品检查 |
| 企业003 | 78项显式HTTP；原生扫描delivered、1候选1证据 | 测评器误从候选列表取evidence_ids，发生KeyError。按真实合同改为独立SQL与evidence API关联，未修改产品 |
| 企业004 | 97项显式HTTP请求、144/144检查 | 完整原生资产到治理部署及真实效果路径通过 |

002说明“注册成功”与“设备可执行任务”必须分开：注册流程能写出文件，后续严格安全读取仍可能失败。这是实际使用限制，不应在方案中以注册200直接关闭设备接入验收。

4个企业批次累计252项评测器显式HTTP；原生Edge内部注册、任务获取、上传和回执请求不包含在这个数字中，不能把252称为全部网络请求。前三批为未完成测量，未执行的业务不是产品防护失败。环境预检和企业批次不合并成功率。

补充复核首次负向注入多加一行空NDJSON，造成解析异常，已保留[复核器错误](enterprise-chain-review-001-error.json)；新review-002修正注入格式，原业务没有重跑或改分。

## 证据与复核入口

- [004预注册修订](../plan/enterprise-chain-004.md)及其引用的001–003设计；[冻结协议](../protocols/enterprise-chain-004-protocol/protocol.json)。
- [004导出证据](../data/enterprise-chain-004/manifest.json)、[原始核验](enterprise-chain-004-verification.json)、[导出核验](enterprise-chain-004-export-verification.json)。导出锚点`f587bb4119348881937abe731246ab005aa8b55e48f49c5084026fb5e11b0364`；私有原始锚点`b459997e1dee8b74e903d0f75927138fccd3b29e28a2fd97c501a227a71148fa`。
- 首次失败记录：[001](../data/enterprise-chain-001/manifest.json)、[002](../data/enterprise-chain-002/manifest.json)、[003](../data/enterprise-chain-003/manifest.json)，均已离线核验且保留`passed=false`。
- [原始命令/接收端/资产交叉复核](enterprise-chain-004-review.json)：6种基于实际数据的错误效果证据被拒绝；另有13种原生身份或网络效果负向单测。
- [导出与资源检查](enterprise-chain-004-export-review.json)：已知私有设备secret、seed无导出匹配；API、网关及本批数据库/sandbox/receiver均已退出或移除。原生临时目录材料已移至项目private目录，临时根不存在。
- [工程验证](enterprise-chain-engineering-validation.json)、[框架回归](enterprise-chain-framework-tests-002.txt)。

## 方案状态与剩余范围

RB12/13/14补齐同候选原生CLI发现到单目标部署、真实执行和回滚的变体。注册仍是源码CLI，身份发行器仍是本批测试issuer，不能提升为正式签名安装包、真实企业IdP或持续发现服务验收。共享目标对其他绑定的影响、并发/丢响应、更多恢复场景、企业UI全链、Windows及其他OS、自然模型确认集与独立第三方复核仍需继续。

总体目标和上述完整旅程保持未关闭；已经通过的单目标链不再因缺少外部条件而重复扩量。
