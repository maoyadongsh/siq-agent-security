# 企业链003状态路径条件修订

沿用001完整业务预期及002接收容器UID修正。002共77个管理HTTP，原生Edge注册成功，但`tasks`返回device_state_unavailable，扫描维持pending，未产生目标候选；后续部署未执行，原始失败保持。

权限诊断确认state目录700、state.json600，但仓库与若干祖先目录775。原生Edge的readDeviceState逐级拒绝非root粘滞目录以外的组/其他可写祖先；这是产品安全条件，不能放宽检查或修改用户工作区权限。也暴露出注册成功与后续状态可读之间的可用性差异，报告保留。

003在/tmp下以mkdtemp创建本批0700独立原生Edge HOME、状态和合成profile，父/tmp为root粘滞目录，符合现有合同。实际注册/扫描/Connector均使用这一路径；运行结束后将本批私有材料移入测评private/runs/<run>/native-edge-private，并记录临时根已移除。最终证据仍全部归档到项目测评目录。候选、97管理请求及6+4专项断言不变，不回改002，不将setup正式安装验收记为通过。
