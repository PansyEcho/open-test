# Change: 故障注入能力与真实数据优先规划

## Why

Fault义务不能简化为`failurePosition=MIDDLE`。要真正命中第N次下游调用，系统必须拥有可验证的真实失败数据，或具备安装、验证、定位和撤销全生命周期的Mock/Stub能力。

## What Changes

- 增加Real Data、Mock、Stub三类Fault能力草稿与正式注册表。
- 增加独立外部Tool Candidate目录和程序脚本协议分析，不复用源码Candidate或metadata声明。
- 程序校验目标Published操作、调用位置、故障结果和撤销能力。
- Fault Planner固定优先选择真实DataSetupRecipe，其次选择Published Mock/Stub。
- Planner只按冻结Entry/obligation身份工作，不接受客户端提交完整Fault语义。
- 增加可复用Fault生命周期执行组件，install成功后的所有路径都在finally撤销。
- 缺少能力返回`BLOCKED_MISSING_FAULT_CAPABILITY`。
- Booking `create-interface-mock.sh`从真实绝对路径解析：安装/更新并返回`mockKey`，但无verify/rollback且存在硬编码QA URL fallback，因此不得发布完整Fault能力。
