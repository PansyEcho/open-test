## MODIFIED Requirements
### Requirement: 真实scriptgen是可执行工具唯一来源
系统 SHALL 将配置的真实scriptgen作为源码发现输入，结合已有Java语义与精确Maven/JAR解析生成接口契约。Facade执行 SHALL 使用已发布DSF声明，不依赖HTTP脚本、业务文件命名或AI解析兜底。

#### Scenario: 成功扫描Facade和Job
- **WHEN** scriptgen返回有效扫描结果
- **THEN** 每个可靠Facade保留请求响应类型、源码位置和source_id；未启用的旧Job规则不影响Facade完整性

#### Scenario: scriptgen不可用
- **WHEN** 配置路径不存在、命令失败或manifest无效
- **THEN** 扫描任务失败并给出精简诊断，不生成伪造工具

#### Scenario: 入口与工具数量核对
- **WHEN** 扫描完成
- **THEN** Facade目录由有效发布声明与框架入口生成，退役HTTP工具不进入执行目录

## ADDED Requirements
### Requirement: 程序解析与可靠结果发布
系统 SHALL 复用源码与实际classpath中的精确依赖类型解析请求、响应、继承与泛型，记录缺失类型位置及已解决或不适用诊断。可靠接口、资源、契约与关系 SHALL 在部分完成时发布到现有表；latest指向当前固定版本最近一次成功发布的扫描，失败扫描不得替换可用结果。任务 SHALL 冻结扫描和契约版本。

#### Scenario: 依赖DTO不在本项目源码
- **WHEN** Facade使用精确依赖JAR中的JobRequest
- **THEN** 程序解析traceId、operator、jobName、startDate、ext及依赖版本，不调用AI

#### Scenario: 局部缺失和恢复
- **WHEN** 单个DTO确实不可解析
- **THEN** 对应目标显示明确缺口，其他可靠接口仍可用；补齐实际依赖后程序重新扫描恢复且历史Case不变

#### Scenario: 通用入口和MQ关联
- **WHEN** 项目更换名称或包名并通过XML、注解或继承发布接口和Listener
- **THEN** 使用相同扫描路径识别入口并把MQ资源关联真实处理方法
