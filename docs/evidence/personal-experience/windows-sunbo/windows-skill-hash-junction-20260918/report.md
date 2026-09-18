# Windows Skill 哈希目录链接逃逸修复

源码 `b00012a4e75929abd76dec6ef5e2a0b3f1312695`。本机普通用户 NTFS 夹具，不提权、不改变系统设置、不使用模型调用。

原失败用例停在无法创建 file symlink。换为明确标注的真实目录 junction 后，发现实际缺陷：Go HashSkillDir 拒绝根外链接，Python 验证器却返回成功哈希。修复前的失败及原始日志摘要保留于 `before-fix.json`，没有以跳过代替修复。

Python 现在通过 lstat 识别 junction/symlink，在目录遍历前排除链接；根外链接拒绝，根内目录链接不递归、不重复计入哈希，未知重解析类型显式拒绝。普通文件内容哈希算法未变，Go 生产实现未修改。规格见 `docs/windows-skill-hash-reparse-spec-v1.md`。

干净源码验证结果见 `verification.json`：

- 普通树 Go/Python 哈希对等、真实根外 junction 拒绝、根内 junction 不重复哈希通过。
- 临时夹具用固定测试密钥签名后可验证；加入根外 junction 后被判为 incomplete，不能因原有签名而接受。此密钥不代表正式发布者，未修改内嵌发布公钥。
- skillmanifest 整包 31 个测试通过、3 个失败、1 个跳过；真实退出码 1。跳过项为缺少源码目录内制品的 `TestResolveStagesVerifiedBinary`，不记为通过。
- 格式检查无输出，vet 通过；四目标构建通过，逐个核验源码 SHA 与 `vcs.modified=false`。非 Windows 三目标还编译了完整 skillmanifest 测试，验证平台文件拆分；交叉编译不表示其他 OS 实机通过。
- 新原生二进制对当前 Skill 自扫描退出 0、结果 `admit_with_conditions`，未 quarantine。该结果不表示已授权执行或完成安装。
- 临时 junction 随测试清理，只删除链接本身；目标数据保持不变。原生自扫描状态保留在私有测试根用于复核；没有新服务、计划任务或日常配置改动。

## 仍失败的发布一致性检查

改动验证脚本改变了 Skill 内容。仓库中的 v0.2.0 正式签名清单仍绑定旧内容；清单、公钥及签名字节均未更改。以下三条检查实际失败于内容摘要不匹配，不能当作通过：

1. `TestCommittedReleaseManifest`
2. `TestAdapterAndBootstrapShareVerifiedResolve`
3. `TestPythonVerifierAcceptsCommittedRelease`

当前修复是未签名源码候选。不能重写旧摘要或使用测试密钥冒充正式签名；新包需维护者按新版本和源码身份在私有暂存目录签名。本轮不发布制品，也未更改旧发布快照。签名不会自动证明宿主支持或验收完成。

这些失败与上一批 MSYS Python/sh 环境失败的原因不同。最终统一候选必须保留并明确处理签名依赖，不能删除或放宽上述检查。本报告不声明整模块、四平台安装或三个真实宿主通过；唯一台账 303 项分母和现有通过数不变。

## 复现

在普通用户 Windows NTFS 隔离目录设置 TEMP/TMP，将原生 Python 3 与 Git shell 明确放在测试 PATH 前，然后在 Go 模块运行：

```powershell
go test -count=1 -run 'TestPythonHashSkillDir|TestPythonVerifierWindowsJunction' ./internal/skillmanifest
go test -count=1 ./internal/skillmanifest
```

第一条覆盖本批实际正负向；第二条保留发布清单不匹配的三个失败。Windows 夹具是目录 junction，其他 OS 保留原 file symlink 用例，不把两者专有行为的覆盖相互冒充。
