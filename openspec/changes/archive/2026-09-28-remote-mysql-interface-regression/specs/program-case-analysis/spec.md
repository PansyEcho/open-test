## MODIFIED Requirements

### Requirement: 语法事实不足时不得提升为核心业务义务

系统 SHALL 仅将resolved可达、明确来源于入口参数且处于受支持控制流路径的证据编译为可求值的程序决策义务。只有单参数方法的全部可达调用均证明相同直接实参来源时，才允许跨helper传播入口字段；有查询来源、条件调用、重赋值、转换或歧义时必须保留未知。内部状态影响的真实决策 SHALL 形成不可删除的Requirement与SemanticGap，而不是伪装成入口参数决策。

#### Scenario: 内部查询结果参与循环
- **WHEN** foreach集合来自数据库查询结果而不是入口请求字段
- **THEN** 不生成请求字段的空/单/多BoundaryObligation，保留内部来源诊断

#### Scenario: 可达辅助方法读取自身参数
- **WHEN** 数据库结果或入口子对象被传入可达helper但分析器没有证明完整调用实参传播链
- **THEN** helper字段保持`method_parameter`，其真实分支形成SemanticGap，不能升级为`entry_parameter`的Decision

#### Scenario: 单参数直接透传入口子对象
- **WHEN** helper全部可达调用均已解析，且都直接传入相同入口字段路径
- **THEN** helper中的有限字段谓词投影到入口路径，原方法、源码位置和调用边仍保留

#### Scenario: 类名看似MQ发送器
- **WHEN** 调用只能通过类名或方法名猜测MQ语义且没有精确框架类型或DSF绑定
- **THEN** 不生成已确认MQ EffectObligation，并记录副作用绑定缺口

## ADDED Requirements

### Requirement: 框架适配必须保留操作身份和静态能力边界

系统 SHALL 在固定源码扫描中识别已解析Mapper或MyBatis SqlSession调用，关联精确namespace.id XML、静态表名、SET赋值列和可证明Spring数据源Bean链；识别精确CacheClientHA调用表面与SOF Producer.send类型。数据库只读查询和Redis只读命令 SHALL 不被登记成写副作用。动态SQL、OGNL、动态资源、topic、异常门控和不受支持的控制流 SHALL 保留明确未知；不得宣称修改行数、发送成功、事务结果或动态分支已被静态证明。

#### Scenario: MyBatis更新语句带WHERE身份
- **WHEN** update语句给state赋值并以id限定行
- **THEN** 覆盖事项记录state为修改列，id不因WHERE等号被登记为修改列

#### Scenario: 动态条件位于嵌套SQL引用片段
- **WHEN** MyBatis的if、choose、foreach或bind位于include引用闭包中
- **THEN** 动态条件随片段展开传播为未知，不因原statement子树没有该节点而认为条件已确定

#### Scenario: 存在提前退出或查询结果门控
- **WHEN** 发送调用之前存在无法完整求值的return、throw、try或其他控制流门控
- **THEN** 激活条件保持未知，不能用一个看似false的根请求字段删除观察责任

#### Scenario: SOF本地事件路由到Listener
- **WHEN** fireEvent参数静态类型唯一对应BaseListener事件类型
- **THEN** 扫描保留需运行时确认的候选分派边并检查listener主体，不把候选路由当作已执行证据

#### Scenario: 资源无法唯一绑定
- **WHEN** 适配器识别到写调用但资源Bean或topic不能由固定声明证明
- **THEN** 保留副作用义务和资源未知，不凭系统仅有一个资源猜测真实目标
