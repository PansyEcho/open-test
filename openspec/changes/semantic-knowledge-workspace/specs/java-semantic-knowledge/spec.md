## ADDED Requirements

### Requirement: Java知识使用可替换语义分析契约

系统 SHALL 通过版本化、解析器无关的语义结果消费Java方法、直接字段关系、调用边、注解、类型/常量Javadoc、枚举和值绑定。无法解析的调用或字段 SHALL 保留原因与置信度，不得升级为已验证知识。

#### Scenario: 多入口复用同一业务方法

- **WHEN** 两个以上知识入口解析到同一个业务符号
- **THEN** 系统只创建一个稳定公共逻辑节点
- **AND** 各入口通过调用边引用该节点

#### Scenario: 动态调用无法解析

- **WHEN** 调用依赖反射、动态代理或缺失类型
- **THEN** 语义结果保存`unresolved`及原因
- **AND** 知识生成器不推断唯一目标或模式

#### Scenario: 类型直接引用领域对象

- **WHEN** 一个Java类型直接声明领域对象字段或领域对象集合字段
- **THEN** 语义结果保存声明类型、引用类型、集合标记和源码位置
- **AND** 知识访谈可展示该直接关系，但不得推断业务所有权、生命周期或未证明基数

### Requirement: 状态机展示业务描述与稳定常量

系统 SHALL 从枚举声明字段、构造赋值、getter绑定和常量Javadoc中解析状态描述，并同时保存稳定常量。构造字段唯一绑定优先于常量Javadoc，二者都不可用时保持未解析常量。

#### Scenario: 枚举使用name字段

- **WHEN** `PENDING_APPLY`构造值明确赋给声明的`name`字段
- **THEN** 状态展示为`待申请（PENDING_APPLY）`

#### Scenario: 描述字段无法证明

- **WHEN** name、desc或description不存在、为空或绑定冲突
- **THEN** display name回退为枚举常量

#### Scenario: 常量注释优先于构造描述

- **WHEN** 枚举常量自身有有效Javadoc，无论是否同时存在name/desc/description绑定
- **THEN** 系统以常量Javadoc作为该值的`CODE_DEFAULT`含义并保留源码证据

### Requirement: 枚举自动形成可修订代码默认值

系统 SHALL 把枚举建模为独立`BUSINESS_ENUM`，分别保存业务名称和逐值含义来源。类注释或Java枚举名 SHALL 形成默认业务名称；每个值 SHALL 依次采用常量注释、唯一高置信构造描述或稳定code。代码默认来源 SHALL 与`USER_CONFIRMED`人工知识保持隔离，且枚举字段不得生成集中问答问题。

#### Scenario: 枚举常量有业务注释

- **WHEN** 枚举常量同时具有业务注释和不同的构造描述
- **THEN** 系统以注释形成`CODE_DEFAULT`业务含义并允许后续人工修订
- **AND** 不生成名称或值确认问题

#### Scenario: 枚举常量缺少注释

- **WHEN** 常量没有有效注释
- **THEN** 系统优先使用唯一高置信构造描述，否则以稳定code形成`CODE_DEFAULT`
- **AND** 重扫更新代码默认值但保留既有人工业务含义

#### Scenario: 枚举缺少业务类注释

- **WHEN** 类级注释为空、仅含作者日期、空Description或模板文字
- **THEN** 系统暂用Java枚举名作为`CODE_DEFAULT`业务名称并进入业务枚举目录
- **AND** 不生成名称确认问题

#### Scenario: 人工修订一个枚举字段

- **WHEN** 用户通过兼容修订入口修改业务名称或某个具体值
- **THEN** 系统只把该名称或该值来源记为`USER_CONFIRMED`
- **AND** 其他值继续保留自己的`CODE_VERIFIED`或`CODE_DEFAULT`来源

#### Scenario: 同名枚举来自多个全限定类型

- **WHEN** 同一简单名对应两个以上全限定枚举类型
- **THEN** 系统以全限定常量标识分别展示代码默认值，不把任一类型冒充唯一业务类型
- **AND** 不生成逐类型或逐值维护问题

#### Scenario: 人工值跨同名类型冲突重扫

- **WHEN** 人工修订某个枚举值后，同简单名类型冲突在后续扫描中出现或消失
- **THEN** 系统按值级源码全限定符号把`USER_CONFIRMED`含义迁移到对应常量
- **AND** 无法唯一归属时保留原人工值并标记候选需要复核，不得静默覆盖或丢弃
- **AND** 只要任一名称或值仍为`USER_CONFIRMED`，候选不得回退为纯`CODE_VERIFIED`

#### Scenario: 旧术语候选迁移为业务枚举

- **WHEN** 旧YAML缺少新字段且下一次语义发现证明其为枚举
- **THEN** 系统保持原候选ID、存储路径、状态、人工备注和源码证据并迁移为`BUSINESS_ENUM`
