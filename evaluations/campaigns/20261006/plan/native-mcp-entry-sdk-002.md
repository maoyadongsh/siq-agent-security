# MCP 原生入口：隔离补齐 SDK 后的接续协议

前批native-mcp-entry-001已终止，3个单元均unknown、0实际MCP调用；原Hermes环境缺可选mcp包，输出Unknown toolsets: mcp-reports。原环境与首次封套保留，锚4b2364c106df489049cdbfc9c197545908c1f633066fbb355baca794c4efb353。不能视为SIQ拒绝或通用MCP不可用。

本批native-mcp-entry-sdk-002沿用[初始协议](native-mcp-entry-001.md)的三单元、预算、原生调用、效果评分及预期门禁。唯一环境变化是测评专属PYTHONPATH依赖目录；按宿主pyproject.toml声明安装mcp 2.0.0、httpx2 2.7.0、starlette 1.3.1及解析依赖，实际全量文件清单在新协议中冻结，运行与离线核验均逐项复查。原宿主venv不修改。

依赖导入已预检；不代表实际注册、工具可见或调用成功。运行仍以真实CLI与stdio记录为准；若仍未注册或发生新异常，保留unknown/失败并定位，不放宽检查。此为显式SDK配置下的结果，不能回填默认安装表现。无真实模型推理。独立签名与来源约束的要求不改变。
