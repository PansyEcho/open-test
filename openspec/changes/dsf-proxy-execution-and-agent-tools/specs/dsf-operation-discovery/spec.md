## ADDED Requirements

### Requirement: DSF操作按系统源码发现并人工确认

系统 SHALL 从当前项目生产配置和Facade源码生成带证据的客户端Profile与provider操作候选，不得把其他项目资源或测试构造混入当前系统。

#### Scenario: 扫描Refund.Core

- **WHEN** 当前源码发布RefundFacade且未声明TiDB
- **THEN** 目录包含RefundFacade的DSF操作候选
- **AND** 不包含Booking.Core的TiDB、Oracle目录或客户端身份

#### Scenario: QA配置无法唯一解析

- **WHEN** 客户端名称、注册中心或发布版本存在冲突或未解析占位符
- **THEN** 候选保持未确认并展示证据和阻塞原因
- **AND** 不生成可执行绑定
