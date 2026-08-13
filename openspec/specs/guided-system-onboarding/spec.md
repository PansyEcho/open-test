# guided-system-onboarding Specification

## Purpose
TBD - created by archiving change v2-guided-console-and-system-onboarding. Update Purpose after archive.
## Requirements
### Requirement: DSF系统注册自动建立扫描任务

系统 SHALL 根据源码目录名生成默认系统ID，保存本地QA Token，并在注册成功后提交Facade、Job、MQ和状态机扫描任务。

#### Scenario: 注册新的DSF系统
- **WHEN** 用户填写系统名称、有效源码路径和Labrador QA Token
- **THEN** 系统返回不可变系统ID与scan_task，Token仅写入0600本地忽略文件且不出现在响应和日志

#### Scenario: 更新现有系统
- **WHEN** 用户更新名称、源码路径或Token
- **THEN** 系统ID保持不变，更新成功后提交新扫描任务

### Requirement: 本地设置仅允许回环访问

系统 SHALL 只向回环地址提供Labrador Token读取和更新能力。

#### Scenario: 非回环客户端访问本地设置
- **WHEN** 请求来源不是127.0.0.0/8或::1
- **THEN** 系统在读取文件前拒绝请求且不返回Token存在性

### Requirement: 扫描结果形成可浏览目录

系统 SHALL 按Facade、Job、MQ Consumer、状态机和知识候选分类展示扫描历史与当前知识状态。

#### Scenario: 查看Booking.Core最新扫描
- **WHEN** 最新Manifest包含90个Facade、36个Job、5个MQ Consumer和1个状态机
- **THEN** 目录保持相同数量并展示19条状态流转及源码证据

