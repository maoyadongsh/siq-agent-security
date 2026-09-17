# Windows 首次任务准备、组合安装与完整性边界

## 结果与候选

干净源码 `185a0d6b9c8d6e17e00e169855273d2644c11a0f` 的 Windows 原生二进制完成首次准备、分步生命周期、`setup`、重复调用及源/系统 XML 篡改拒绝实测。实际程序 SHA-256 为 `5776d67d784c7131a7eb88faef1c26a8dbe939e5140fd2634603d4625fce9d2c`。构建元数据确认源码未修改；本目录后续新增的是证据。

这些证据覆盖固定台账 P03-TASK-01、06、08、12、13、16、17，不能代替三个宿主的受保护执行链或最终集成候选回归。任务实际没有触发器；没有执行注销登录、重启、关机、睡眠测试。

## 问题与修复

原候选 `3b37589bd5e670401bfa255311573a883fec8749` 在新状态 `init` 后导出 XML 正常，但首次 `task-prepare` 因缺钥保护拒绝。Windows 准备流程提前创建的生命周期锁被识别为已有历史。原始失败见 `first-use-before-fix.json`；显式先建立身份后完成的历史生命周期见 `repeat-lifecycle.json`，不把它作为首次准备成功。

修复先在主 Writer 内调用原有 `signing.Load`，释放后再按生命周期锁、主 Writer 的原有顺序取得双锁，通过 `LoadExisting` 读回并比对公钥，最后准备任务。未修改共享签名保护，不忽略或删除锁文件，不恢复丢失的历史私钥。历史缺钥、已签任务丢钥、主 Writer 和生命周期锁冲突均有负向测试。

## 原生证据

| 文件 | 实际验证 |
| --- | --- |
| `first-use-fixed.json` | 全新状态无需预先 `pubkey`；XML 导出不注册且文件摘要不变；独立 Ed25519 验签、SID/程序/状态路径/实例一致；重复注册、启动、停止、注销；唯一进程和监听；停止后空闲；注销缺席、历史保留 |
| `setup-fixed.json` | 独立全新状态组合安装就绪；系统定义与分步流程在归一实例名、状态路径后相同，归一前逐项核对实际身份/路径；重复 setup 保持同一进程；停止注销后文件摘要不变 |
| `tamper-fixed.json` | 源 XML 加固定注释后注册/启动/注销均在明确完整性校验层拒绝；系统任务 Description 改动后同样拒绝；每次拒绝后本地文件摘要、系统 XML、实例数、最近运行时间不变，无进程/监听；精确恢复后正常查询并注销；真实 Triggers.Count=0 |
| `console-close.json` | 专用隐藏 Windows Console 启动任务；核对独占控制进程和原生窗口句柄后 WM_CLOSE 关闭，控制台消失，SIQ 同一进程/监听继续运行，健康身份复验通过；正常停止注销 |
| `port-evidence-review.json` | 重新核对原候选 ebc472f2 的端口占用证据及 manifest 摘要，满足 TASK-09 的不误报就绪/不替换占用者要求；不是当前候选重测 |
| `probe-diagnostic.json` | 首次篡改探针在只读检查阶段将 COM 返回的账户名直接与 SID 比较，尚未篡改即失败；经独立诊断改为账户名解析 SID 后重测。两批均已注销，不把控制器失败记为产品失败 |

所有状态在专用私有目录创建，父目录 DACL 保护继承，仅当前 SID、SYSTEM、Administrators 三个 ACE。此隔离措施不是产品 ACL 缺口已修复的证据。所有“文件不变”仅指相对路径到 SHA-256 的文件快照，不扩大为所有元数据或 ACL 恒定。

每批使用实例专属任务名，系统篡改只针对本批从未运行、空闲且身份/动作/原 XML 精确匹配的任务。恢复只接受本批写入的精确字节。各批最终任务缺席、所属进程与监听为空；状态和私有原始记录保留以供审计。无额外模型调用，未操作日常实例。

## 复现步骤

1. 从上述源码 SHA 创建独立干净 checkout，原生构建 `./cmd/agentshield`；记录源码 SHA、`go version -m` 和实际程序摘要。使用新的当前用户私有测试根、含空格/中文的状态目录及空闲 loopback 端口；设置进程级 `SIQ_AGENT_SECURITY_STATE_DIR`。
2. `init --port <port>` 后执行 `task-xml`，比较前后文件摘要并用 `task-presence` 确认不存在；随后直接 `task-prepare`。使用公钥独立验证任务记录规范化 JSON 的 Ed25519 签名，并将 XML 中 SID、路径、实例与实际输入核对。
3. 依次执行 `task-register --confirm-register`、`task-start --confirm-start`、`task-stop --confirm-stop`、`task-unregister --confirm-unregister`，每项重复一次。用系统读回及 CIM/端口所属 PID 验证，不能只看 CLI 退出码。结束确认任务缺席、无自有进程/监听，状态文件保留。
4. 另建新状态执行 `setup --confirm-setup --port <port>`，验证系统定义和分步流程一致；重复 setup 不增进程，然后停止注销。
5. 再建新状态，只准备注册不启动。通过 Task Scheduler COM 读回当前用户任务，将账户名解析为 SID 后核对归属、动作、路径、参数、空闲状态及零实例；核对触发器数量。
6. 分别对源 XML 加固定注释、对系统任务 Description 加固定标记，每次只改变一种。注册/启动/注销必须退出 1 且分别返回记录中的明确完整性错误；比较本地快照、系统 XML/实例/最近运行时间，并确认无程序或监听。恢复精确原始配置后正常查询，最终注销。不要修改未知任务或重签被篡改记录。

## 检查口径

旧代码新增首次准备测试失败；修复后负向测试和 27 项顶层 Windows 测试通过、无跳过。fmt/vet、四目标构建、锁定 Python 环境 214 项 Schema 通过。详细退出码与摘要汇总在 `verification.json`。

完整 Windows Go 回归退出 1：16 个失败包，其中 skillinstall 达到 20 分钟包累计超时，报警时当前测试仅运行 6 秒，不能推断为该测试死锁；server 完成但失败。相关 race 退出 0。完整检查使用专用非 AppData 私有 TEMP/TMP，未提升权限或关闭防护。证据提交 7699794 的远端检查为 39 成功、3 跳过，不以局部通过或远端 CI 代替本机完整验收。共享资源绑定和 ACL 问题不在本修复中解决；最终集成候选尚未确定。

## 超时后补齐与控制台复现

`skillinstall` 的完整包运行在累计 20 分钟超时时截断。按原测试枚举顺序，从当时刚运行 6 秒的测试开始还有 37 项；分为 13/13/11 项三批、每批上限 10 分钟、最多并行两批，保留全部原断言。三批均退出 0，37 项顶层测试全部通过，无顶层或子测试跳过。见 `skillinstall-tail.json`。此前完成的失败及完整运行 exit 1 仍有效，没有改写成全套通过。

控制台复现使用原生 Python 启动专用 `CREATE_NEW_CONSOLE` 控制进程并隐藏窗口；由控制进程执行 `task-start`，结束后读回 `GetConsoleProcessList` 必须只包含自身 PID，并记录自己的 `GetConsoleWindow`。父进程确认对应 `ConsoleWindowClass`、同一进程句柄存活和 SIQ 服务就绪后，仅对此 HWND 发送 WM_CLOSE。等待控制进程退出且 IsWindow=false，再核对原服务 PID、监听和目录健康。该证据覆盖本批原生 Windows Console 关闭，不外推人工操作 Windows Terminal 标签页。

初次控制台探针因 Python venv 启动器额外进程被独占检查拒绝；独立无 SIQ 调用的对照确认 venv 为两个控制台进程、原生解释器为一个，因此新批改用原生解释器后完成。初次任务已停止注销，失败原始记录与修正原因均保留。
