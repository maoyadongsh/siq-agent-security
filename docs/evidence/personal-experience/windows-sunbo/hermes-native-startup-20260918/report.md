# Windows Hermes 原生 CLI 启动等待修复

产品源码 de5de5f72d5a9a5f60323334f038abbae6c80ad1；后继8ab38b5只增加超时负向测试。实际入口为本机已安装 Hermes 的 venv/Scripts/hermes.exe，入口哈希见 verification.json。所有配置命令均在本批 HOME/HERMES_HOME/插件副本中执行，无模型请求，不接触日常 profile。

旧8秒预算：原有原生opt-in测试正向失败，报CLI不可用/不兼容。独立同环境配置查询实际9.829秒后exit0、返回正确合成文档、stderr0，证明该机器启动超出了预算。负向旧测试也接近8秒，不能以旧测试pass声称验证了配置拒绝语义。

规格先行将Windows每命令上限设为30秒，其他系统仍8秒。保持输出限制、隔离副本、无模型及错误拒绝；不增加权限、不改变原生配置事务与运行时授权。

修复后三项真实CLI测试全部通过，无跳过：启用插件并保留用户新增配置、卸载恢复原登记；拒绝非法YAML/列表/alias输入；全新profile启用。控制器166.63秒，退出0，临时目录无遗留。配置证据不能替代真实工具执行、完整多实例保留或保护链自检。

新增Windows实进程负向：专用测试子程序先写启动标记并输出部分JSON，然后等待2分钟；实际产品调用在30.06秒后ErrNativeCLI、返回结果为空，未把部分JSON作为配置结果。完整adapterinstall包exit0，顶层数量及跳过逐条见verification.json。跳过包括独立已验证的native opt-in与实际无法构造的符号链接等前置，保留原始结果，不宣称全零跳过。

格式和vet通过；Windows原生及Linux amd64/arm64、Darwin arm64构建、锁定Schema校验退出0。完整集成七包原有失败仍保留，不将本包通过改写为全项目成功。固定台账68/303通过、4失败、8受阻、223未测；3项系统中断排除。本次修复是必要接入前置，不提升未覆盖的完整宿主旅程。

复现：固定源码，使用已安装可信CLI的绝对路径设置SIQ_HERMES_NATIVE_CLI，私有TEMP/TMP；执行go test -json -count=1 -timeout=10m -run ^TestHermesNativeCLI ./internal/adapterinstall。然后去除该opt-in变量，执行整包回归（含30秒实际超时负向）；真实CLI已单独验证，不因包内跳过丢弃该结果。所有本批配置查询子进程已退出。
