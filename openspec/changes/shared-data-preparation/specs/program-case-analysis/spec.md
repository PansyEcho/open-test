## MODIFIED Requirements

### Requirement: 扫描bundle必须完整校验后原子发布

系统 SHALL 验证manifest及其system、scan、baseline和入口引用后原子发布扫描；ProgramCaseAnalysisCatalog SHALL 不再是生产扫描的必需输出或latest发布条件。

#### Scenario: Catalog写入失败
- **WHEN** 当前扫描manifest有效而旧程序Case分析资产缺失或不可生成
- **THEN** 扫描仍可发布有效manifest，不以缺少覆盖义务阻塞系统接入
- **AND** 不以空Catalog伪装完成Case分析

#### Scenario: 调用方尝试只发布manifest
- **WHEN** 生产扫描提供有效且完整的manifest
- **THEN** 存储层允许更新latest，Case场景与预期留待Case生成阶段产出
- **AND** 历史程序分析文件保持可读且不被删除

## REMOVED Requirements

### Requirement: 程序Case分析必须由独立scan绑定资产提供
**Reason**: 扫描阶段不再维护必经回归点、语义义务或覆盖清单。
**Migration**: 保留历史资产；当前流程使用固定Operation结构与源码证据，场景和预期在Case生成时分析。

### Requirement: 语法事实不足时不得提升为核心业务义务
**Reason**: 扫描阶段不再维护必经回归点、语义义务或覆盖清单。
**Migration**: 保留历史资产；当前流程使用固定Operation结构与源码证据，场景和预期在Case生成时分析。

### Requirement: Semantic Draft必须覆盖完整缺口分母且不能删除程序义务
**Reason**: 扫描阶段不再维护必经回归点、语义义务或覆盖清单。
**Migration**: 保留历史资产；当前流程使用固定Operation结构与源码证据，场景和预期在Case生成时分析。

### Requirement: 冻结清单只能由服务端可信资产组装
**Reason**: 扫描阶段不再维护必经回归点、语义义务或覆盖清单。
**Migration**: 保留历史资产；当前流程使用固定Operation结构与源码证据，场景和预期在Case生成时分析。
