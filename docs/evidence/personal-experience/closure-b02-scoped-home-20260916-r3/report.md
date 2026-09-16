# closure-b02 证据报告（installed systemd 用户服务承载完整旅程）

- 时间：2026-09-16T11:14:58+08:00
- 任务层：test_release（测试信任根）；正式发行信任腿未关闭，解锁条件 = 维护者以正式发布种子签署 manifest。
- 控制面：installed_user_service（client-install / service-start / service-stop / teardown / pair），全程无 Popen(binary serve) 回落。
- 结果：15 PASS / 0 FAIL

## 检查

- [PASS] `b02_build_and_manifest` 测试信任构建 + manifest 签署（test_release 层）
- [PASS] `b02_unit_local_home` running service HOME is fixture; shared manager unchanged
- [PASS] `b02_install_via_client_install` 客户端安装注册并启动 systemd 用户服务（受支持入口）
- [PASS] `b02_no_second_daemon` 旅程开始时唯一 serve 进程来自本批状态目录
- [PASS] `b02_discovery_binds_fixture_instance` daemon 实例发现指向隔离 HOME 的 fixture 实例（非日常 profile）
- [PASS] `b02_journey_installed` installed systemd 服务承载 r07 完整浏览器旅程（含 R04 嵌套腿）
- [PASS] `b02_identity_preserved_across_restarts` 重启前后 state_directory_id/unit/端口/摘要/加载源不变且 MainPID 变化
- [PASS] `b02_stop_via_service_stop` journey 后 service-stop 正常停止且幂等路径确认
- [PASS] `b02_teardown_unit_gone` teardown 后 unit 注销（加载源消失）
- [PASS] `b02_state_retained_after_teardown` teardown 后状态目录与记录保留（含签名 user-service 记录）
- [PASS] `b02_reentry_same_state` 同状态重入：state_directory_id/版本不变，回执历史保留
- [PASS] `b02_reentry_receipts_preserved` 重入后回执链历史完整（历史保留）
- [PASS] `b02_final_teardown` 最终 teardown：unit 再次注销
- [PASS] `b02_ownership_reverified` ownership 复验：无遗留本产品 unit，状态目录仍归本批
- [PASS] `b02_direct_regression` direct_process 腿回归：r07 main() 原样通过

## 阶段身份（同一实例绑定）

- installed_start: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=410649 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- pre_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=410649 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- post_stop: active=inactive main_pid=0
- post_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=418333 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- post_stop: active=inactive main_pid=0
- pre_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=418333 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- post_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=420205 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- pre_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=420205 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- post_stop: active=inactive main_pid=0
- post_restart: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=420426 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- journey_done: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=420426 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…
- post_stop: active=inactive main_pid=0
- reentry: unit=siq-agent-security-7d1b5fd2e5a824f713da4f2a95bf022d.service pid=421392 state_id=ad8b4b5aa9007347… digest=593b236ea5cb…

## direct_process 回归腿

- r07 main() 原样执行：passed=True checks=25

## HOME 隔离

- working-tree 模式使用签名 unit 的实例 HOME 并读取运行进程复验；只读比较 manager 环境不变。
- 不满足前置条件时阻塞，不回退直接启动或修改 unit drop-in。
