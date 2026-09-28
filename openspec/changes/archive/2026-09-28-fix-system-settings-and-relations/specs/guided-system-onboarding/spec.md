## MODIFIED Requirements

### Requirement: DSF系统注册自动建立扫描任务
系统 SHALL 根据源码目录生成默认系统ID，保存资源配置环境并在注册成功后扫描Facade及MQ。已有系统的普通配置保存 SHALL 只修改名称和环境，不提交扫描或更换代码基线；系统身份及源码路径 SHALL 保持固定。系统 SHALL NOT 要求或消费Labrador Token及HTTP Job网关。

#### Scenario: 注册新的DSF系统
- **WHEN** 用户填写系统名称、有效源码路径及资源配置环境
- **THEN** 返回不可变系统ID与scan_task，且无HTTP Job设置门禁

#### Scenario: 更新现有系统
- **WHEN** 用户进入编辑并保存名称或资源环境
- **THEN** 返回保存的系统，系统ID、源码路径、代码基线及扫描数量保持不变，旧HTTP Job配置不进入请求或响应
- **AND** 扫描器不可用不阻止元信息保存；旧auto环境在未重新选择时保留

#### Scenario: 拒绝通过普通编辑切换源码
- **WHEN** 客户端通过系统更新接口提交不同源码路径
- **THEN** 后端拒绝修改且保持原配置；更新代码基准需使用独立的显式操作
