# Windows Writer 崩溃恢复修复

关联 Issue #79；当前 Windows 任务依用户更新的目标承担修复。查重时 Issue 无主修、无实施 PR。先合入 main e386c99，再固定源码候选 `84c84a1d990f3783c2afe53e9a9657f6c21b4ffd`。

Windows 原实现对其他正 PID 一律返回存活，导致真实服务崩溃后无法继续写入。现在以只读 SYNCHRONIZE 进程句柄、零等待确认死亡；未知/权限拒绝/越界 PID 保持拒绝。回收在禁止共享的同一文件句柄内读锁、查进程、按句柄排他重命名，避免按路径回收时误移动并发新锁；保留旧锁字节。

新增测试覆盖真实子进程崩溃、24 个竞争申请者、探测期间替换/改写/第二回收尝试、活动 PID、拒绝访问与异常等待、PID 范围、硬链接/损坏/超预算锁、目标已存在、中文空格长路径。定向测试通过；不把这些组件测试冒充宿主旅程。

## Windows 原生 SIQ 服务复验

`daemon-verification.json` 记录 20 个断言：旧 de5 程序初始化并健康运行；新程序拒绝抢占；只终止本批自建服务；旧程序恢复仍失败；新程序恢复成功且保留旧锁；新程序再次运行并异常退出后也可恢复；配置、实例、状态标记及已有密钥的摘要不变；最终签名 stop 成功、服务退出 0、主锁释放、端口关闭。没有触碰桌面宿主、日常服务、系统登录会话或付费模型。

旧程序 SHA256：`08b43f749f716d042a4d2a3a0219e605a9ebeee05f5eda66c742de9064f67658`。新程序 SHA256 见验证 JSON。脚本 `run-daemon-recovery.py` 使用工作区相对的两个已固定自建产物和排他新建测试根，不能在未知目录或日常实例上执行。原始服务日志留在本机私有目录，不提交。

## 回归状态与限制

格式、vet、Windows 构建通过。独立 state 全包检查因 300 秒预算耗尽返回 1；耗尽发生在并发版本测试，不能记为整个 state 包通过。已完成的真实提交崩溃恢复与 Writer 安全负向通过；迁移仍报告 checkpoint 重入错误及只读权限断言失败，后续在独立迁移修复候选继续处理。完整 `go test ./...`（每包 15 分钟）、三平台交叉构建及 Schema 校验由仍运行的控制器继续，不伪报完成。

此修复不解决 ACL、宿主资源授权、OpenClaw 会话绑定或完整迁移/升级旅程。验收分母保持 303，本批不把局部恢复证据改计为整项通过。进程 PID 复用为活动进程时保持拒绝；不承诺抵御任意同用户替换父目录。Windows 新实现拒绝非常规锁对象，非 Windows 延续原有回收策略。

API 依据：[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)、[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)、[SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)、[FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)。
