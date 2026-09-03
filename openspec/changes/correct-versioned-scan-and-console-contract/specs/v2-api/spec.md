## MODIFIED Requirements

### Requirement: API覆盖单系统闭环

FastAPI SHALL 通过`/api/v2`提供系统配置、扫描、知识、资源、Operation、Case Generation与独立Execution接口，不再提供Scenario、Snapshot、MVP、Suite或历史Case编译与执行入口。

#### Scenario: 从扫描到显式执行

- **WHEN** 调用方依次配置系统、扫描、发布知识、创建Generation并显式创建Execution
- **THEN** Generation和Execution保持`system_id`、`source_scan_id`、`generation_id`与`execution_id`追溯链
- **AND** 只有Execution入口允许Case流程访问QA

#### Scenario: 调用已移除的Case路由

- **WHEN** 调用方请求历史Scenario、Snapshot、typed Case、Hybrid Case或单Variant执行路由
- **THEN** 服务返回`404`
- **AND** 不创建任何Case或访问QA
