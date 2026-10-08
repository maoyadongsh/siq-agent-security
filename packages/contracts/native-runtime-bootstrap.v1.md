# 受保护原生运行初始化 v1

这是 Linux OpenShell 镜像 profile 的运行端初始化接口，供受保护启动代码调用，不是模型、Skill、普通插件或 HTTP 管理入口。宿主仍须按 native-runtime-image-profile/v1 固定镜像、解释器、启动参数、初始化模块和实际 PID；仅调用这个 Python API 不构成可信部署。

## 初始化顺序

1. `ImageBootstrap(agent_id, session_namespace, channel_directory)` 接收启动器固定的非秘密配置，不读环境变量、模型参数、任意 JSON 配置或可替换回调。agent_id 与 namespace 使用原生 Runtime 的严格格式；channel_directory 为规范绝对路径。
2. 当前进程必须 Linux、非 root，真实与有效 UID/GID 一致。逐级 NOFOLLOW 打开目录，排他创建本次 0700 通道叶目录；不复用、覆盖、chmod 或删除已有对象。保留目录描述符与路径身份，拒绝符号链接和可被其他用户写入的祖先（root 的 sticky 临时目录除外）。
3. `ready()` 返回 `native-runtime-bootstrap-ready/v1` 描述：pid、uid、gid、agent_id、session_namespace、channel_directory、runtime_state=unverified。宿主只把它作为定位线索，必须独立核验实际进程、启动制品及目录，不能信任自报 PID/主体。
4. 宿主完成实际运行登记和通道创建后，`configure(timeout=30)` 在最多 60 秒内等待该目录内的固定 `native-host.sock`。对象必须为同 UID/GID 的 0600 socket；此检查仅用于启动协调，不代替身份认证。
5. 安装固定的 HermesChannel、Callbacks.via_host 和 Runtime。客户端逐包强制验证服务端 `(pid=0, uid=本进程UID, gid=本进程GID)`；所有实际事件仍由宿主内核凭据、Go Authority、来源和权限链重新核验。初始化不发起授权、不建立假任务、不自行登记会话，也不返回允许裁决。

启动器在 configure 返回之后才进入现有 Hermes gateway/业务入口。原生 run_conversation 继续从实际任务和 session 建立作用域；初始化器不手工指定 Skill，不伪造会话与调用事实。

## 失败和资源边界

每进程只允许一次初始化尝试；重复初始化、fork 后调用、目录或端点不符、超时、回调通道失效均失败关闭，不尝试旧插件、HTTP 直连或替换主体。初始化器不持有运行凭据、管理凭据或签名私钥。目录与 socket 本身不是信任根，任何消息仍要通过逐包服务端凭据校验。

目录描述符存活期间反复核对路径身份和权限；观察/决策交换前后都检查。`close()` 只关闭本次描述符并使后续交换失败，不删除目录或宿主 socket、不重新开放初始化。已开始的外部动作不因 close 而被宣称回滚；整体沙箱清理由所属启动器负责。

覆盖包包含初始化模块并把其摘要纳入制品；任何变化生成新候选。原有普通插件不自动导入本模块，旧 mount profile API 不变。业务配置、provider 凭据、网关启动及 model loop 由业务仓库原有受保护入口负责，不通过本接口接收任意可执行模块或命令。

实际 OpenShell 工具联验可以先验证这个初始化组件；完整业务入口、真实业务 Skill、模型和跨平台验收仍需单独完成，manifest 不因此自动标记 production_enabled。
