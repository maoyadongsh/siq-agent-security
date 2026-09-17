# Windows 阶段计时测试可移植性

关联 Issue #62。源码提交 `1947a614377fc23317cf2745734be132230854df`，基于 main `d4850f52988b52b9399a1e8889891f624edf7eea`。保留原 `.tmp/win-timing-20260915` 草稿，当前仅复用其测试修改；不改生产引擎、授权时钟或回执。

规格 §阶段计时要求单调性能时钟、仅记录实际进入的阶段及保持授权语义；并未要求每个短阶段严格大于零。原 Windows 测试已收到多个 0s 样本，却以 duration <= 0 误判为 missing。干净 main 定向基线在 optional/required 两条路径均失败，见 before.log。

现在继续要求实际阶段恰好一个非负样本、未执行阶段零个样本，以及启用观察器前后 action/reason_code 一致。只有受测 IntentLookup 回调加入有界等待，直到单调时钟可测量至少 2ms，再单独要求该阶段记录相应耗时。没有给生产计时填最小正数，没有修改分母或新增 Skip。

为确认断言没有退化成只检查回调存在，在本批隔离树临时将 stageTimer 改用已冻结的授权时钟，两个分支均在“lookup timing must advance despite frozen authority clock”处失败。反向验证之后恢复引擎原始字节并确认摘要；此故意错误实现没有进入提交。

修复后定向测试、CGO/GCC 启用的 race 测试、完整 receipt 包（122.745 秒）均退出 0；gofmt 无输出、receipt vet 和 diff-check 通过。退出码、原始日志摘要及命令见 verification.json。仅为测试变更，未构建新交付程序或重复全模块测试；其他 Windows 完整回归失败仍保留，不把本包通过扩展成三个宿主或最终集成候选通过。
