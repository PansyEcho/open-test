## MODIFIED Requirements

### Requirement: 扫描动态读取本地运行与系统网关设置
系统 SHALL 在扫描提交时动态解析scriptgen路径和资源配置环境；系统 SHALL NOT 读取HTTP Job网关或Labrador Token，不生成旧HTTP Job执行入口。

#### Scenario: 普通DSF系统无HTTP网关扫描
- **WHEN** 用户未配置旧HTTP Job Token或网关而提交DSF系统扫描
- **THEN** Facade及MQ发现正常进行
- **AND** `CommonFacade#executeJob` 等DSF方法仍作为Facade保留

#### Scenario: 历史HTTP Job产物被调用
- **WHEN** 客户端尝试执行旧job_http_trigger操作
- **THEN** 系统拒绝已退役路径，且不调用HTTP脚本
