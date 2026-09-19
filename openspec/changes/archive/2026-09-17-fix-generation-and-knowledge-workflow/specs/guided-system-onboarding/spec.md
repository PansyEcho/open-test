## MODIFIED Requirements

### Requirement: DSF系统注册自动建立扫描任务
系统 SHALL 根据源码目录生成默认系统ID，保存资源配置环境并在注册成功后扫描Facade及MQ。系统 SHALL NOT 要求或消费Labrador Token及HTTP Job网关。

#### Scenario: 注册新的DSF系统
- **WHEN** 用户填写系统名称、有效源码路径及资源配置环境
- **THEN** 返回不可变系统ID与scan_task，且无HTTP Job设置门禁

#### Scenario: 更新现有系统
- **WHEN** 用户更新名称、源码路径或资源环境
- **THEN** 系统ID保持不变并提交新扫描，旧HTTP Job配置不进入请求或响应

### Requirement: 本地设置仅允许回环访问
系统 SHALL 只向回环地址提供本地资源环境设置读取和更新，不再公开旧HTTP Job Token及网关。

#### Scenario: 非回环客户端访问本地设置
- **WHEN** 请求来源不是127.0.0.0/8或::1
- **THEN** 在读取文件前拒绝请求

### Requirement: 扫描结果形成可浏览目录
系统 SHALL 在知识库统一展示接口与字段契约目录；系统配置页仅保留扫描操作及版本状态，不重复展示完整结果树。

#### Scenario: 查看系统最新扫描
- **WHEN** 用户打开系统配置页
- **THEN** 可以刷新扫描状态或重新扫描，并进入知识库浏览Facade及MQ契约
- **AND** 不展示公共逻辑、状态机或逐方法依赖缺口列表
