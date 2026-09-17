Windows 定向复验确认一个新增测试的平台假设，受测源码为 `9cc18630be584692905e1ce612b91a9ba5aee610`，独立检出前后 clean。Windows 11 amd64、Go 1.27.1、CGO=0；只运行新候选的三个 adapterinstall 测试，没有启动 Hermes、模型或用户现有服务。

```text
go test ./internal/adapterinstall -run '^Test(HermesControlledInstallPathChecksBeforeNativeInstall|HermesNativeEvidenceSeparatesRegistrationFromCompatibility|ConfiguredEndpointReadsConnectionDocumentOnly)$' -count=1 -timeout=90s -json

PASS TestHermesNativeEvidenceSeparatesRegistrationFromCompatibility
PASS TestConfiguredEndpointReadsConnectionDocumentOnly
FAIL TestHermesControlledInstallPathChecksBeforeNativeInstall
install_entry_test.go:82: controlled install command missing: open <PRIVATE_TEST_ROOT>/.local/bin/hermes-skills-install: The system cannot find the path specified.
```

退出码 1。原因是 [新增测试](https://github.com/maoyadongsh/siq-agent-security/blob/9cc18630be584692905e1ce612b91a9ba5aee610/apps/agentshield/internal/adapterinstall/install_entry_test.go#L74) 无条件要求 shell wrapper 存在且权限为 0700，而 [实际实现](https://github.com/maoyadongsh/siq-agent-security/blob/9cc18630be584692905e1ce612b91a9ba5aee610/apps/agentshield/internal/adapterinstall/plan.go#L439) 仅在非 Windows 生成它；后续 0700/admit 顺序断言本次尚未执行。

建议分开验证：POSIX 保留先 admit 后原生安装的断言；Windows 验证 wrapper 不生成、预览明确说明受控安装入口缺失、没有冒充安装拦截。Windows 入口仍应保留待交付状态，不能通过简单跳过把这一能力记为完成。这是新增测试的可移植性问题与已有能力缺口，以上两个诊断测试通过也不提升原生宿主验收。

原始 go test JSONL 留在本机私有测试根，SHA256 将随下一批证据归档；没有修改本 PR 的共享文件或受测原始输出。
