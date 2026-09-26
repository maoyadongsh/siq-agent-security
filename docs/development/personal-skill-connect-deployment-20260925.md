# 个人端连接优化部署（2026-09-25）

按用户明确部署指令，已将现有个人端 `http://127.0.0.1:47611/overview` 切换至 `0.4.0-dev-connect`。这是本机源码候选部署，不是正式签名安装或公开发布；企业端未改动。[本批候选与证据](../evidence/personal-experience/skill-connect-deploy-20260925/candidate.json)。

## 实际运行

| 项目 | 读回 |
| --- | --- |
| 新进程 | PID `820429`，原 PID `171047` 已正常退出 |
| 新程序 | `var/flagship/skill-connect-deploy-20260925/siq-agent-security` |
| 程序 SHA-256 | `02acea34b368e7dfa693826f17e0133309609c0bcf940da6559f55689a8916e2` |
| 状态目录 | 沿用 `.tmp/flagship/as01-state-v2-20260921`，目录身份不变 |
| 原数据 | 372 个原文件部署切换后逐项摘要匹配（运行锁除外）；12 份运行身份读回一致；回执链验签及内容一致 |
| 浏览器 | 新连接入口、375px 布局、显式确认、24 小时 Cookie、刷新不续期、退出失效、无 JavaScript 错误，共 7 项通过 |
| 企业端 | API 与 Web 容器仍 healthy，未重启 |

切换前核对无活跃 HTTP 连接、无未过期的本地请求身份，备份原状态和环境。使用 pidfd 精确停止已核对的原进程，确认 Writer 释放后启动候选，沿用原环境，包括 Hermes 上下文。没有重新签发 Grant 或业务身份，没有执行模型任务。

部署浏览器测试只建立并退出一次临时管理会话，不替用户批准业务动作。测试后原审计前缀保留、新审计只追加；其他原文件保持不变（运行锁除外）。本次重启使旧浏览器会话失效，用户需刷新页面，通过智能体确认或手动配对重新连接。

## 复核与回退

本批私有备份、原环境、运行日志和脚本位于 `var/flagship/skill-connect-deploy-20260925/`，目录权限 0700，已被 Git 忽略；其中含真实凭据，不可公开或提交。候选程序已从 `.tmp` 复制至上述持久部署目录，未改系统服务或开机自启。

执行记录：`/usr/bin/python3 var/flagship/skill-connect-deploy-20260925/deploy.py`、`.tmp/k001-browser-venv/bin/python var/flagship/skill-connect-deploy-20260925/browser_check.py`、`/usr/bin/python3 var/flagship/skill-connect-deploy-20260925/preservation_check.py`。一次性切换脚本不可重复运行；原始脱敏结果保存在同目录 `deployment.json` 和 `browser-check.json`。

原程序保留为 `var/flagship/report-generation-20260924/agentshield-linux-arm64`，SHA-256 为 `334367d16defb46cfc7f6bebe233048f87574c9e55ecd81e2f17dfbcbb6eafea`。如需回退，先重新核对运行 PID、程序摘要、Writer 和在途请求，再正常停止本候选，使用保存的原环境及原程序启动同一状态目录和端口。不得用备份覆盖当前状态或删除新增审计；回退后便捷连接入口及 24 小时会话将不可用。本批没有执行真实往返回退。

本次授权只部署个人端，不包含 Git 提交、公开发布、新签名包、批量改写宿主 Skill 安装或企业业务授权。源码候选及 README 仍在原工作树，后续签名发行需独立固定身份和验收。
