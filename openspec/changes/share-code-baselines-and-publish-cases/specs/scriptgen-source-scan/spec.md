## ADDED Requirements

### Requirement: 语义调用边必须区分反射目标与普通接口调用

系统 SHALL 仅在接收者可证明是反射 API（`java.lang.Class`、`java.lang.reflect.Method`、`java.lang.reflect.Constructor`）时把调用标记为反射目标；普通业务接口中名为 `invoke` 或 `newInstance` 的方法 SHALL 按普通调用解析。Bean 分派 SHALL 遵守实际解析语义：显式 `@Resource(name=...)`/Bean 名称优先，未显式命名的 `@Resource` 先使用字段默认名称，并考虑继承字段；只有显式名称和默认名称都不能确定时才按唯一类型回退，存在多个候选时保持未解析。

#### Scenario: 业务接口 invoke
- **WHEN** 源码字段或局部变量声明为普通业务接口类型，并调用其名为 `invoke` 的方法
- **THEN** 生成普通调用边，而不是 `reflection_target_not_static`

#### Scenario: 反射 API
- **WHEN** 调用可解析为 `Class.forName`、`Method.invoke`、`Constructor.newInstance` 等等价反射接收者
- **THEN** 保持未解析的反射原因，不把它伪装成业务调用边

#### Scenario: Resource 分派
- **WHEN** 调用接收者是 `@Resource` 字段
- **THEN** 先尝试显式名称，未显式命名的 `@Resource` 使用字段默认名称，并查找继承字段
- **AND** 只有显式名称和默认名称都不能确定时才按唯一类型回退；多个候选保持未解析

#### Scenario: 外部参数类型
- **WHEN** 方法参数类型来自依赖，且简单名只有通配符 import
- **THEN** 扫描器不猜测唯一限定名；除非固定依赖 classpath 或单类型 import 证明该类型，否则方法或调用边保持未解析或部分解析
- **AND** 单类型 import 可用于补全精确描述符；通配符 import 或同名简单名猜测不被接受

#### Scenario: 显式服务注解分派
- **WHEN** 入口方法传入服务枚举常量，且实现类声明显式服务注解
- **THEN** 只有在完整路由键（包括 resourceType、source 和默认值）以及注册与查找关系都被证明时才新增调用边
- **AND** 仅匹配枚举常量或类名不得创建该边
