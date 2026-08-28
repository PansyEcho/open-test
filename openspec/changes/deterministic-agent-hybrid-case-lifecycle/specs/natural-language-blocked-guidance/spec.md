## ADDED Requirements

### Requirement: Case状态必须提供统一业务展示投影

系统 SHALL 为Web、CLI和API提供包含状态、标题、摘要、缺失项、影响、建议动作、范围及折叠技术信息的统一投影。

#### Scenario: 缺少可取消退票单准备方式
- **WHEN** cancel需要可取消退票单但没有正式Producer Recipe
- **THEN** 主视图说明缺少可取消退票单的查询或创建流程，技术码和资产ID仅出现在技术详情

#### Scenario: 查询没有命中数据
- **WHEN** QUERY_ONLY明确返回未找到且Action尚未执行
- **THEN** 页面显示本次缺少可用前置数据，不把结果描述为业务断言失败
