# Design

候选目录只投影最新不可变扫描bundle中的语义方法、入口、DSF引用和资源证据。方法身份来自语义分析的`symbol_id`；缺少完整语义分析时，仅把扫描器已经确认的入口投影为候选，不重新解析或猜测源码。Candidate详情关联语义类型中的字段、集合属性、校验注解和源码引用，搜索结果仍可复用同一只读模型。

`SystemDependencyBinding`按`consumer_system_id -> provider_system_id`保存直接发现授权，角色为`UPSTREAM`或`DOWNSTREAM`，用途为Setup、Action、Oracle、Fault或Cleanup中的至少一种。绑定不反向、不传递，不授予发布、Recipe引用、QA或执行权限。provider必须是另一个活动注册系统；删除绑定后旧Candidate ID立即不可访问。系统更换源码路径时绑定可以保留，但新扫描完成前该provider范围明确阻塞。

跨系统搜索返回consumer及每个直接绑定provider自己的`source_scan_id`、完整`SourceBaseline`、绑定身份和状态。程序逐系统读取scan bundle并核对注册基线；任一范围缺少latest、bundle不完整或基线漂移时整体`complete=false`并返回具体blocker，不静默忽略。详情查询同样按当前直接授权范围重新校验。

MQ入口规则采用结构化“全局内置 + 系统Git覆盖/追加”：规则声明精确FQN注解类型或父类/接口、真实handler方法、参数数量及payload位置。系统规则只能来自当前系统Git根下固定的`source-rules/mq-framework-rules.yaml`，文件或祖先含符号链接、解析后越界时整个扫描失败。扫描器只遍历排序后的`src/main/java`生产源码，只在规则唯一匹配到文件顶层具体非抽象类直接声明且payload位置有效的handler时创建Entry，并在metadata保存rule ID、匹配owner、handler和源码证据；测试/生成源码、符号链接、接口/枚举内嵌类、其他嵌套类、注释/调用表达式、同简单名类型、无规则或歧义均不创建Entry。生产规则允许声明某个系统自己的抽象MQ基类FQN及`process`，但不得包含任何目标Listener类名。

每个Candidate保存所属`system_id`、`source_scan_id`和完整`SourceBaseline`。Entry先在精确owner上解析唯一完整contract签名，再只能关联唯一具体实现；零实现、多实现和重复Candidate身份分别以PARTIAL或源码blocker拒绝，不按列表顺序选取。后续发布阶段必须重新读取所属系统扫描并核对基线、签名及DTO；Candidate本身的`executable`字段是字面量`false`，Recipe和执行器没有Candidate ID入口。本阶段把能力草稿、Setup、Fault、Cleanup和V3执行写入口固定为对应`NOT_REBUILT` blocker，不读取本地QA绑定、不执行残留READY资产且不写后续阶段注册表。
