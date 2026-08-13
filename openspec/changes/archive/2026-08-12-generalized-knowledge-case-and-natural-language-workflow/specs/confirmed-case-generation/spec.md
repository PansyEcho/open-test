## ADDED Requirements

### Requirement: 回归Case必须经过场景矩阵人工确认

系统 SHALL 先生成场景矩阵并等待显式确认，再生成业务Case和执行步骤。

#### Scenario: 首次生成全量回归
- **WHEN** 用户从已确认知识发起Case生成
- **THEN** 系统只返回覆盖目标、场景矩阵、优先级和能力缺口，尚不创建可执行步骤

#### Scenario: 确认矩阵后生成Case
- **WHEN** 用户确认矩阵且所有必要知识可用
- **THEN** 系统生成自包含业务Case及数据准备、业务调用、逐实体断言、聚合断言和清理步骤

### Requirement: 缺失条件不得被猜测或绿色通过

系统 SHALL 在Fixture、关键枚举、脚本或结果校验能力不足时把相关Case标记为BLOCKED并列出具体缺失条件。

#### Scenario: 港币多乘客缺少价格Fixture
- **WHEN** 场景需要成人儿童不同报价但当前Fixture没有对应引用
- **THEN** Case保持BLOCKED且说明缺少的业务数据，不生成空断言或默认价格

### Requirement: 人工Case资产不可被全量生成覆盖

系统 SHALL 把生成资产与人工维护资产分开，并保留现有31个Booking.Core自定义Case的内容与稳定ID。

#### Scenario: 重复生成全量Case
- **WHEN** 用户对同一扫描再次生成场景矩阵和Case
- **THEN** generated资产按稳定ID增量更新，`cases/custom`内容摘要保持不变
