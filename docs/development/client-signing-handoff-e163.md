# E163 受控签发交接

客户端功能冻结在本地候选提交 `fd02384d6de5f96a849f9d04bbfbfaff38cf6148`，分支 `codex/flagship-client-0.4.0-rc.1-e163`。候选版本 `0.4.0-rc.1` 尚未签发、打标签或发布。签发入口正在等待用户提供；不要在聊天、命令参数或文档中填写私钥正文。

## 签发前已准备

- 固定源码隔离构建，内嵌 UI 重建完全一致，四平台二进制摘要固定。
- 独立源码 Go 44 包、前端 53 文件/290 项、发行工具 15 项通过。
- Linux ARM64 最终构建空状态启动/配对/页面/停止，以及真实 systemd setup 专项通过。
- 原分支和已有改动保留，候选工作树干净；企业 API/研究业务部署不包含在客户端提交范围中。

## 旧版升级基线已核验

已从固定 0.3.1 Release 获取八个资产，使用原官方根验证 Skill 签名、内容与四平台二进制 pin，包/单文件及安装说明一致。Linux ARM64 旧版在临时状态中的启动、配对、控制台与停止通过。仅准备升级源基线，尚未执行旧版到新候选的升级或回滚，也没有替换已安装服务。

证据：`var/flagship/ux-e163/upgrade-baseline-verification.json`。

## 受控入口应执行的命令

前提：已批准的现有秘密存储只向此打包进程提供 `SIQ_AGENT_SECURITY_RELEASE_SEED`；使用原发行密钥，不创建新信任根。以下命令本轮未执行，缺密钥时不能取得签发成功结论。

在 `/home/maoyd/siq/siq-agent-security` 运行，输出路径必须尚不存在：

```bash
python3 scripts/release/package.py \
  --source-root /home/maoyd/siq/.worktrees/siq-agent-security-client-e163 \
  --source-sha fd02384d6de5f96a849f9d04bbfbfaff38cf6148 \
  --version 0.4.0-rc.1 \
  --out-dir /home/maoyd/siq/siq-agent-security/var/flagship/ux-e163/signed-release \
  --sign

python3 scripts/release/verify.py \
  --release-dir var/flagship/ux-e163/signed-release \
  --version 0.4.0-rc.1 \
  --source-sha fd02384d6de5f96a849f9d04bbfbfaff38cf6148 \
  --report var/flagship/ux-e163/signed-release-verification.json \
  --native-smoke
```

打包工具会验证既有官方根、实际 Skill 内容与四目标二进制 pin。环境内密钥不传给 npm/Go 构建和普通验证子进程。普通校验和、SOURCE-INFO 与跨平台编译都不代替发行签名或原生安装验收。

## 签发后剩余验收

1. 用签名包在独有状态/HOME/runtime 用户服务中走 `client-install`，核对实际运行程序和清单摘要、实例身份、健康、配对和页面；不替换用户现有安装。
2. 以已验签 0.3.1 离线包建立旧实例，经真实 `service-upgrade` 进入新候选；检查签名身份、授权/撤销历史和记录保留。拒绝篡改、错版本、错源摘要；不借恢复参数绕过身份检查。
3. 按升级事务调用受支持回滚，核对实际运行版本及状态兼容性。若回滚被状态兼容门禁拒绝，记录真实限制，不回写历史状态伪造通过。
4. 停止并注销本轮归属单位后才删除夹具。签发及这些验证均不等于批准合并、推送或对外发布；远端发布需要对应授权及资产回读。

不继续增加本轮客户端功能。原标杆项目的生产 IAM、业务部署与故障恢复、原生 CI 和后续安全任务仍独立记账。
