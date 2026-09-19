## MODIFIED Requirements

### Requirement: API覆盖单系统闭环

FastAPI SHALL 提供系统与扫描、独立接口契约、共享数据方法、Case生成与显式执行、统一任务和运行报告接口；当前流程 SHALL 复用本地存储及已有Generation，不要求先发布内部知识或额外创建Snapshot。

#### Scenario: 从扫描到执行
- **WHEN** 调用方从固定扫描创建Case或独立数据准备任务，再显式执行选定版本
- **THEN** API保留system、scan、方法版本、task、generation和execution的可用关联
- **AND** 方法定义与本次业务ID分开保存，生成期间不调用QA

#### Scenario: 独立自然语言数据任务
- **WHEN** 原生Agent搜索共享方法并选择明确版本执行
- **THEN** 与Case使用同一数据服务，输入条件与allow_writes原样提交，结果可从数据执行接口读取
- **AND** 同一request_id不得因重试创建第二笔业务数据
