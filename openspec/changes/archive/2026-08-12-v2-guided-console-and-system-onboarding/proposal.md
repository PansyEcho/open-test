# Change: V2引导式控制台与系统接入

## Why

当前V2控制台把注册、资源、知识、场景和执行堆在同一页面，真实扫描得到的Facade、Job、MQ Consumer与状态机没有可浏览目录。资源页还把每个MQ生产者和消费者误当作独立连接，并以Oracle等内部术语向用户暴露实现细节。

## What Changes

- 建立保留V2视觉风格的左侧导航控制台，按用户工作流拆分独立页面。
- DSF系统注册默认使用源码目录名作为ID，保存本地Labrador QA Token并自动提交全量源码扫描。
- 提供扫描历史、分类目录和知识状态查询。
- 按NameServer配置聚合MQ连接资源，生产消费关系进入详情。
- 将公开Oracle命名替换为“结果校验能力”，提供可点击详情抽屉和兼容API。
- 资源连接采用临时Worker探测；连接状态和业务校验状态分别展示。

## Scope

本change只开放DSF系统注册和一期单系统页面，不实现WEB扫描或跨系统关系。真实QA业务Case仍由等待输入的`dsf-execution-and-oracles` change管理。

## Non-Goals

- 不迁移现有`train-booking-core`系统ID。
- 不执行真实创单或补造QA Fixture。
- 不删除legacy V1页面或API。
- 不在本change实现通用深层知识生成和Case三阶段生成。
