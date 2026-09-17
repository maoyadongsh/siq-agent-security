# Windows 标准 Schema 测试入口

固定候选 810e8e93df747ac91c9e1a9eccd3294c1a20490c（base b303c6f92392f3a44c306d81ad7323c6291ef4f2）上的原标准命令正式通过：206 passed、1 warning；相关 ruff 通过。此次只将 conftest.py 顶层的 app.main 导入延迟到现有 client fixture 内，Schema 用例未请求该 fixture 时即可正常收集。生产 fcntl/signing、Schema、锁定依赖及测试分母均未修改，未使用 --noconftest 或新增 skip。[Issue #59](https://github.com/maoyadongsh/siq-agent-security/issues/59)。

| 阶段 | 状态与结果 |
| --- | --- |
| 原 b303 基线 | 标准命令 exit 4；conftest 导入链缺少 fcntl，尚未开始测试。 |
| 单文件 dirty 开发验证 | 同一命令 exit 0，206 passed、1 warning；pytest 自报 16.87s。 |
| 干净候选正式验证 | 同一命令 exit 0，206 passed、1 warning；pytest 自报 5.44s，命令耗时 9.252s。 |
| 正式相关 ruff | exit 0，命令耗时 0.399s。 |

在 apps/control-api 目录执行的命令为：

- uv run --locked pytest app/tests/test_schema_contracts.py
- uv run --locked ruff check app/tests/conftest.py app/tests/test_schema_contracts.py

环境为原生 Windows 11 / AMD64、CPython 3.13.7、uv 0.12.13。新工作树创建独立锁定 venv；正式验证沿用同批新 venv，editable 元数据仍绑定该工作树，没有复用旧批 venv。准备阶段一次字节断言因 Git 写出 CRLF 停止，发生在补丁后测试之前；保留原件，随后仅核对归一 LF/AST，没有重新应用补丁。正式候选采用 LF。

唯一警告是 StarletteDeprecationWarning（现有 httpx 与 starlette.testclient 组合弃用提示），本次未以安装依赖消除警告。正式命令前后 HEAD 与 clean 状态一致；五个相关文件 bytes/SHA 前后未变。独立复核重新计算准备 30 条、正式 16 条原流摘要，核对返回码和元数据，未发现差异。23 条记录中的持有命令均已自然回收，无 timeout/kill；本公开包只保存角色和摘要，不搬运原始 traceback。

详情见 [开发基线](development-baseline.json)、[干净候选验证](clean-validation.json)、[独立核验](verification.json) 和 [文件清单](manifest.json)。

这补齐 Windows 标准 Schema 入口证据，不代表整个生产 Control API/signing 支持 Windows，也不代表三宿主验收。Linux client-fixture 生命周期回归仍等待未来 PR 精确 head 的 control-api CI；本批没有运行或推定该项通过。
