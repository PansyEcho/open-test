## ADDED Requirements

### Requirement: 扫描动态读取本地运行与系统网关设置

系统 SHALL 在每次扫描提交时动态解析scriptgen运行路径和当前系统QA Facade网关前缀。显式扫描前缀优先；未显式提供时使用当前系统本地设置。系统不得把Labrador Token传入扫描请求或共享产物。

#### Scenario: 普通DSF系统使用注册时保存的网关扫描

- **WHEN** 用户已为普通DSF系统保存QA Facade网关前缀并提交扫描
- **THEN** scriptgen命令的`--facade-http-prefix`使用该系统前缀
- **AND** 生成的Facade工具能够构造默认URL
- **AND** 扫描参数、任务和Manifest不包含Labrador Token

#### Scenario: 缺少网关时扫描前阻塞

- **WHEN** 扫描请求与本地系统设置都没有QA Facade网关前缀
- **THEN** 系统在启动scriptgen前返回可操作的配置错误
- **AND** 不发布失败扫描为latest Manifest
