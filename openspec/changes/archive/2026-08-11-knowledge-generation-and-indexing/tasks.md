## 1. 知识分析模型

- [x] 1.1 增加知识生成批次、代码符号和确认请求模型
- [x] 1.2 实现Java类、方法、注解和关键条件证据定位
- [x] 1.3 实现createOrder入口、Validator、ServiceInvoker和Builder纵向追踪

## 2. 节点、关系与问题

- [x] 2.1 生成入口、公共逻辑、业务规则、状态机和依赖节点
- [x] 2.2 生成同系统calls/depends_on/reads/writes/transitions关系
- [x] 2.3 批量生成高影响待确认问题并支持人工回答
- [x] 2.4 发布知识并重建SQLite索引

## 3. Agent与入口

- [x] 3.1 实现只读、环境白名单和超时受控的AgentRunner
- [x] 3.2 增加CLI知识生成、确认和查询命令
- [x] 3.3 增加FastAPI知识生成与确认接口

## 4. 验证

- [x] 4.1 增加纵向追踪、人工保护、问题确认和索引查询测试
- [x] 4.2 对真实createOrder生成知识并验证深层港币规则证据
- [x] 4.3 运行strict校验、V2与legacy测试
- [x] 4.4 更新系统Skill、架构和开发状态
