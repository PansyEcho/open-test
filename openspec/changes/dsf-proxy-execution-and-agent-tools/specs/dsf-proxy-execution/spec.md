## ADDED Requirements

### Requirement: Facade通过扫描绑定的DSFProxy操作执行

系统 SHALL 在QA环境把已确认的Facade逻辑工具解析为当前扫描绑定的DSF操作，并通过独立Java Worker使用被测系统客户端身份调用。请求不得携带动态服务地址、凭据或未确认服务描述。

#### Scenario: 被测系统调用自身只读Facade

- **WHEN** Booking.Core确认并执行自身`OrderFacade.orderDetail`操作
- **THEN** Worker从绑定目录解析gsName、service、version和action
- **AND** 使用Booking.Core客户端Profile返回结构化脱敏结果

#### Scenario: Agent调用其他已扫描系统

- **WHEN** Booking.Core确认调用Refund.Core的`RefundFacade.queryListByOrderNo`
- **THEN** 目标描述来自Refund.Core provider扫描，调用身份仍属于Booking.Core
- **AND** 未确认的跨系统操作在启动Worker前被拒绝

#### Scenario: 请求夹带服务描述

- **WHEN** 请求payload包含gsName、service、version、action、Token或注册中心地址
- **THEN** 文件协议确定性拒绝请求且不初始化DSF客户端

### Requirement: Labrador仅在只读金丝雀前保留

系统 SHALL 仅在DSFProxy验证阶段保留旧脚本兼容；本系统自调用和跨系统只读调用均成功后，新执行不得再读取Labrador地址或Token。

#### Scenario: 两个只读金丝雀完成

- **WHEN** 自调用和跨系统调用均通过注册、路由、序列化和响应校验
- **THEN** 新扫描操作目录只使用`dsf_proxy`
- **AND** 历史脚本Manifest可审计但不可重新执行
