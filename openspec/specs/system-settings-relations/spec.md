# system-settings-relations Specification

## Purpose
TBD - created by archiving change fix-system-settings-and-relations. Update Purpose after archive.
## Requirements
### Requirement: 系统配置具有明确编辑边界
控制台 SHALL 默认以只读形式展示已注册系统，点击编辑后才允许修改名称和环境，提供相邻保存与取消按钮，永久不可变字段 SHALL 保持禁用并可辨识。普通保存 SHALL 不扫描且不依赖扫描器可用，更新代码基准 SHALL 使用独立明确动作。

#### Scenario: 修改名称与取消
- **WHEN** 用户查看已有系统并开始编辑名称后取消
- **THEN** 原值恢复且不发送写请求
- **AND** 保存名称时持久化新名称，退出编辑，基线和扫描数量保持不变

### Requirement: 关系发现区分身份和版本兼容
共享关系 SHALL 在组名、服务、方法及接口符号唯一匹配时识别调用方与提供方，即使版本不同也双向显示。跨版本关系 SHALL 明确标记版本差异，并不得被当作精确匹配来自动扩大执行范围。MQ一对多和歧义约束 SHALL 保留。

#### Scenario: booking引用旧版本refund
- **WHEN** booking引用refund的相同接口但当前发布版本不同
- **THEN** booking可见refund下游，refund可见booking上游，接口关系显示双方版本
- **AND** 不改写扫描、契约或固定Case，不据此声明版本兼容

### Requirement: 控制台重复读取复用有界内存
控制台 SHALL 仅缓存系统列表、扫描目录、关系与知识目录的只读HTTP投影，限制为32项及估算32MiB，并在每次请求检查已有共享版本识别远端变化；契约、后补接口和草稿更新 SHALL 与版本推进同事务提交，使下一次读取失效旧缓存。扫描历史、事务和实时执行判断 SHALL 直接读取真相。

#### Scenario: 连续读取与外部更新
- **WHEN** 用户重复访问相同目录
- **THEN** 命中内存以避免重复传输解析
- **AND** 本进程或其他工作台提交的更新在下一次请求版本检查后可见，回滚写入不改变可见版本

### Requirement: 正常配置隐藏开发诊断噪声
控制台 SHALL 将DSF操作确认及金丝雀诊断移入默认折叠的高级区并按需读取；未接入系统 SHALL 作为普通提示汇总，版本差异、歧义、解析失败 SHALL 各自说明原因和处理方向。上下游展示 SHALL 包括DSF和MQ。

#### Scenario: 打开系统配置
- **WHEN** 用户进入系统页面
- **THEN** 不自动请求旧DSF全局目录，不展示成排红色未接入错误卡
- **AND** 可展开查看接口及来源证据，真实读取失败仍明确可见

### Requirement: 关系目录读取已发布可靠扫描
系统 SHALL 从当前已发布扫描读取已确认关系，包括部分完成的扫描；尚无扫描时返回可解释空态，不抛出manifest不存在错误。

#### Scenario: 新系统及局部扫描
- **WHEN** 系统没有扫描或只有部分完成的已发布扫描
- **THEN** 分别展示空态或已确认上下游，未接入下游仍可见

