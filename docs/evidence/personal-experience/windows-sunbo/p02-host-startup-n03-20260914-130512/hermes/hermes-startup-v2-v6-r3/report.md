# Hermes Windows 公共 CLI 启动诊断 v2–v6

这五轮均未完成 A 的真实文件写入，B 均未运行。v4、v6 已通过未修改的公共 CLI 进入真实 Agent 会话、文件工具分发与工具结果回传，但工具错误和目标文件不存在，不能标为正常执行或 SIQ 失联拒绝通过。

所有轮次使用同一已安装 Hermes 0.21.2、安装自带 Python 和独立 Windows 私有 profile。入口为 `python -m hermes_cli.main chat --provider custom --model siq-synthetic-fixture --toolsets file --max-turns 3 --run-budget 40 --ignore-rules --quiet --oneshot`，查询文本仅要求本地合成测试。实际文件路径和完整 argv 保留在本机私有原始日志。模型服务仅为本次本地合成响应，不调用真实模型账号。

## 逐轮事实

| 轮次 | 子进程观测上限 | 单轮 case 记录耗时 / 退出 | 结果与本轮变化 |
|---|---:|---|---|
| v2 | 35 秒 | 35.234 秒 / exit 1，超时回收 | 0 请求；增加私有详细诊断，不放宽原守卫。15/30 秒线程快照仍在首次 profile 的内置 skills 同步。3 个被拒子进程是 banner 的本地 Git 查询。 |
| v3 | 35 秒 | 35.587 秒 / exit 1，超时回收 | 0 请求；新 profile 使用受支持 `.no-bundled-skills` 标记，仅同步 essential skills。导入 Bedrock 适配器时尝试 lazy installer，在 stdlib 准备 `os.devnull` 的 open 处被守卫拒绝，安装器未启动。 |
| v4 | 60 秒 | 45.823 秒 / exit 0，自然结束 | 新配置 `security.allow_lazy_installs=false`；已记入列表的 12 次本地请求为 10 个 metadata GET 和 2 个 chat POST，第二 POST 包含真实工具错误。另有 2 次 provider 协议断言错误未计入该列表。16 个空设备 open 被拒、3 个 Git 子进程被拒，目标未写入。 |
| v5 | 60 秒 | 60.544 秒 / exit 1，超时回收 | 新增精确空设备例外，但本轮仍在导入，尚未触发例外；0 请求、3 个 Git 子进程被拒。不能据此判断空设备例外无效。 |
| v6 | 180 秒 | 65.547 秒 / exit 0，自然结束 | 与 v5 相同权限，延长观测上限、线程快照间隔改为 30 秒。16 次精确空设备例外生效，19 个真实子进程调用仍全部被拒；列表记录 12 次本地请求，另有 2 次 provider 协议断言错误；真实工具错误回传、目标未写入。 |

表内时间来自每轮 `checks[0].elapsed_seconds`，计时从启动前开始，到通信、provider 回收和日志处理后结束，包含这些开销，不是精确进程生存时间。父 harness 总耗时在 JSON 另列，不能互换。v6 的进程查询发生在自然结束之后，没有证据证明它在 45 秒时已经退出。所有主进程均由 harness 回收；v2–v6 未放行任何 `Popen`，没有将后续轮次的子进程清理能力回填到这些轮次。

## 定位结果和边界

v2 的 Git 命令仅用于 banner 版本信息：两个 `rev-parse` 和一个 `describe`，不是 Git Bash。v3 的空设备访问来自 `subprocess._get_devnull`，发生在 `tools.lazy_deps._run_installer` 尝试准备安装进程时。v1 旧日志只记下事件类别，具体 open 原因仍未知；不能用 v3 的详细日志替 v1 补结论。

v4/v6 的 `protocol_errors` 各记录两个 `AssertionError`，协议断言在向请求列表追加记录之前执行，所以列表计数不是完整 HTTP 请求总量。原始记录没有给出这两次错误的具体原因；材料保留其类型和数量，不把 fixture 错误归为宿主或 SIQ 缺陷。

v4 的堆栈已覆盖公共 CLI → AIAgent → 原生 tool executor → tool registry → `file_tools` → `LocalEnvironment`。Windows 的文件工具实际通过 Git Bash 执行，不能替换成自写 Python 文件工具来声称宿主通过。此轮空设备拒绝发生在 `Popen` 审计事件之前，尚不能据此获得那些 helper 的实际 argv。

v5/v6 仅允许原始路径严格等于本机 `os.devnull`、mode 为 None、flags 为 130，且调用栈来自精确 stdlib `subprocess.py` 的 `_get_devnull`。没有大小写折叠、设备名前缀或其它路径例外。另附 [独立 Win32 检查](devnull-device-check.json)：工作区 Python 3.13.7 以 `os.O_RDWR` 打开空设备，取得句柄类型 2（字符设备），关闭后由 EBADF 验证描述符失效。该检查仅核验设备身份，不是 Hermes 调用或守卫的重放，也不是文件目录写入豁免。v5/v6 所有子进程仍被拒绝。

v6 才取得完整的真实 helper argv：9 个 Git 查询、1 个 Python 版本探测、5 个 Bash 尝试、4 个只读 PowerShell ASLR 查询。Bash 尝试包括 Git 安装路径与 System32 候选的启动检查、登录环境快照、非登录 `true` 回退，以及包含合成目标的登录模式文件预检。这些命令均未执行。没有关闭 ASLR、放开登录 shell、运行安装器或读取日常账号。

profile 配置的被动审计只证明尝试读取该精确文件；审计事件在操作前触发，不能证明打开、解析或应用成功。v4/v6 未观察到 lazy installer 尝试与所配置的禁止行为一致，仍不把配置 effective 值填为 true。`.no-bundled-skills` 是新 fixture 中的受支持 opt-out 标记，不代表验证了公开 profile-create 流程。

## 身份与材料

[summary.json](summary.json) 是按白名单从五份原始报告派生的结果，逐份记录原始报告与 harness SHA、六个安装源码文件的前后校验、宿主 Python SHA、退出码、守卫计数和副作用。旧原件没有覆盖；原始路径、argv、调用栈、模型请求和 stdout/stderr 不直接公开。v2–v5 原报告没有单独观测上限字段，派生材料从摘要匹配的确切 harness 字节读取 `communicate(timeout=...)`，同时保留原字段为 null。

主检出始终为干净 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`。原报告中的 SIQ candidate `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` 与 Windows 二进制摘要只做身份核对，本组没有执行 SIQ 二进制，也没有安装或加载 SIQ 插件。源安装的 `.env`、更新标记仅检查存在性，未读其内容；六个被测关键源码哈希保持不变。

Python 审计守卫是测试约束，不是 OS 沙箱。这组证据用于定位真实宿主启动和执行前提，不提升三宿主原生验收矩阵；后续需先完成真实无插件写入对照，再验证插件加载、服务不可达、宿主消费拒绝结果与目标无副作用。
