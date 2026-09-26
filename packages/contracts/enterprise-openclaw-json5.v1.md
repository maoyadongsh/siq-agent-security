# OpenClaw 静态 JSON5 配置采集 v1

[官方配置参考](https://docs.openclaw.ai/gateway/configuration-reference)使用 JSON5。采集在既有安全打开/预算内，增加纯数据词法转换：行/块注释、尾随逗号、单引号、标识符键（包括 Unicode escape）、JSON5 空白、字符串换行续接/十六进制转义、有限十六进制整数及带加号/前后小数点的十进制。转换后仍经标准 JSON 语法和既有重复键、64 层深度、include 禁止检查，不执行 JavaScript 或环境替换。

转换输入最多 16 MiB、262144 个 token，输出最多 32 MiB；超限/非法语法统一 openclaw_config_invalid，无片段回显。NaN/Infinity、超过 uint64 的十六进制整数拒绝，不作为权限事实；这不是无约束全 JSON5 实现。未知业务字段不构成权限或安装证明。原配置字节而非标准化结果用于证据摘要，注释或格式变化仍生成新观察，角色位置身份不变。

无新运行时依赖、无 Node/JS 解释器要求；仅 OpenClaw 文件配置启用，不放宽设备签名协议或控制面 API 的严格 JSON。默认角色推导继续遵循 enterprise-openclaw-default-role/v1。真实版本配置兼容性与安装验收另行记录。
