## 1. 审查问题修复

- [x] 1.1 网页运行占用全局门禁后RUNNING保存或事务提交失败时释放门禁（`web_generation.start`）；新增`test_web_start_save_failure_releases_global_gate`，修复前复现`another long task is active`。
- [x] 1.2 重放旧扫描时已保存Manifest经`ScanManifest`校验并规范化后比较；新增`test_replaying_scan_saved_before_new_default_field_is_not_a_conflict`，修复前复现“扫描身份已保存不同内容”。
- [x] 1.3 无接收者fireEvent按所在类型及祖先判定SOF派发，不可求解时记录缺口；新增`resolvesUnqualifiedFireEventInheritedFromSofContext`，修复前失败。真实三系统快照复跑SOF告警0、派发候选边与修复前一致。
- [x] 1.4 测试会话在收集前把知识根与元数据读取重定向到会话临时库；新增`test_import_time_default_app_never_reads_workspace_metadata`；未配置测试MySQL时导入模块被跳过。

## 2. 验证与交付

- [x] 2.1 全量回归通过：Python 949 passed / 2 skipped，Node 41/41，Java 34/34；测试实例无残留`ot_test_*`库。
- [x] 2.2 OpenSpec严格校验通过后归档；已停止本轮启动的测试MySQL（33061无监听）；8788为用户既有服务（非本轮启动），未停止。
