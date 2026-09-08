# Provenance-Bound Effect V1 工具链核验

2026-09-08，源码a7502e0，扫描范围apps/agentshield全部包。govulncheck版本固定v1.7.0，安装到临时验证工具目录，不修改项目依赖。

## 实际发现与修复版本复验

原Go1.26.5扫描exit 3，报告5项可达标准库漏洞：GO-2026-6218、GO-2026-6090、GO-2026-6089、GO-2026-5972、GO-2026-5026；扫描输出均指向Go1.26.6修复。原日志/tmp/siq-govulncheck-current.log。

其中URL路径解析的复杂度问题已核对[Go官方漏洞公告](https://pkg.go.dev/vuln/GO-2026-6218)，影响Go1.26.6之前的1.26系列。该公告不能代替其他漏洞的单独报告；其余记录由实际govulncheck结果提供。

使用GOTOOLCHAIN=go1.26.6按Go工具链机制下载到工具缓存，未覆盖全局Go命令。复扫exit 0，输出No vulnerabilities found，日志/tmp/siq-govulncheck-patched.log。

```bash
# 从apps/agentshield执行
GOBIN=/tmp/siq-validation-tools go install golang.org/x/vuln/cmd/govulncheck@v1.7.0
GOTOOLCHAIN=go1.26.6 /tmp/siq-validation-tools/govulncheck ./...
GOTOOLCHAIN=go1.26.6 go test -race ./...
GOTOOLCHAIN=go1.26.6 go vet ./...
```

## CI处理

旧ci.yml为了兼容测试会把漏洞发现记为warning并退出成功，故绿灯不等于无漏洞。本轮新增独立runtime-security-toolchain任务，固定Go1.26.6，扫描非零即失败，并使用修复版本执行race/vet。保留原Go1.22兼容路径，不用自动升级工具链冒充旧版兼容测试。

没有改变main规则、生产部署、已有Release二进制或全局Go默认版本。已有Go1.26.5编译产物仍需要重建才能获得标准库修复；仅新增CI不会修复历史产物。结果不外推到Edge/所有Connector或未来漏洞库。

本地Go1.26.6完整race及vet已通过（/tmp/siq-patched-toolchain-race.log）。新CI任务仍需推送后的真实运行结果。
