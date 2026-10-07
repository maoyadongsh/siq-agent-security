# OpenShell 原生只读镜像与双向内核通道 profile v1

这是 native-runtime-guard/v1 的显式 Linux 镜像 profile，适配本机 OpenShell 0.0.83 实际运行方式。原 bind-mount profile 不变。不能因 Docker 根文件系统可写而省略代码保护，也不能将本 profile 表述为只读根文件系统。

## 镜像中的代码和 Skill

可信启动器固定实际 OpenShell 沙箱/容器归属、完整镜像 ID、代码文件 SHA-256、解释器与启动参数摘要。实际进程必须非 root，NoNewPrivs=1，effective/permitted/ambient capabilities 全零。代码和 Skill 文件从该进程根目录逐级 NOFOLLOW 打开；文件和所有祖先必须由 root 拥有、无 group/other 写权限，目录须保持原对象。攻击者能修改同进程代码、root/内核或可信启动器仍在保证之外。

代码清单最多 128 文件、单文件最多 1 MiB、累计最多 16 MiB；实际文件摘要、链接数和读前后对象状态仍逐次核验。Skill 根逐项登记宿主批准安装根与运行时镜像根；镜像根的完整文件集合必须与本 profile 的清单一致，拒绝额外文件/目录、符号链接和可写对象。Go 实际安装解析仍核对签名 Claim、当前 Grant、宿主源/目标和本次实际读取摘要。镜像内副本不与宿主安装宣称同 inode；对应关系来自可信制品构建、固定摘要与原生真实读取，不是模型提供的路径声明。

底层解释器、库、OpenShell supervisor 的固定镜像身份和非 root 文件保护由必需启动后端证明。不得把 chmod、哈希或单次失败写入独立当作完整可信部署。进程与 namespace 改变、镜像归属失效、当前安装/权限变化继续失败关闭，不缓存先前成功授权。

## 无额外业务挂载的双向通道

可信启动器可在已核验进程的命名空间内创建独有 0700 临时通道目录，并通过固定进程根目录 fd 逐级打开。宿主只复制该目录 fd，以 `/proc/self/fd/<fd>/native-host.sock` 建立 socket；不跟随任意调用者给出的宿主符号链接，不改变 OpenShell 业务挂载合同。目录须由当前宿主用户与实际非 root runtime UID/GID共同对应，路径、inode 和私密权限在后续核验中固定；关闭仅删除该 fd 内本实例创建且 inode 一致的 socket。

运行时客户端明确固定响应的 SCM_CREDENTIALS：宿主与容器在不同且已验证的 PID namespace 中，宿主服务端 PID 在容器视图中为 0，UID/GID 须为启动器固定值。发送方向仍由宿主校验实际 Hermes 的宿主 PID 和 UID及 pidfd。返回包的身份、帧或序号不符使客户端失效；不回退为仅信路径。容器内同 UID 进程替换 socket 路径会得到可见的非零发送 PID，必须被拒绝。该方案允许临时目录本身对运行时可写，只保证其不能因此伪造宿主响应；删除端点可造成拒绝服务，不能授予权限。

此变体只适用于宿主原始 PID namespace 对容器不可见的已核验部署，不对任意命名空间拓扑通用启用。客户端原来的只读目录信任模式保持默认；镜像 profile 的可信 bootstrap 必须选择上述固定响应凭据，且 bootstrap 自身被制品/启动参数核验。创建通道目录、修改镜像和注入回调都不是工具或模型接口。

独立临时 OpenShell 网关和本次沙箱可用于验证；不能替换现有业务网关、改旧镜像、重配现有挂载或将平台特定证据扩展为 Windows/macOS 支持。产品入口仍须实际联通并完成两 Skill 日常业务验收。
