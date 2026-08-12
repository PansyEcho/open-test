## 1. 基线与产物契约

- [x] 1.1 增加扫描请求、状态机、工具和扫描产物领域模型
- [x] 1.2 实现Git分支、commit、dirty摘要捕获
- [x] 1.3 实现扫描ID、产物目录和manifest持久化

## 2. 真实源码扫描

- [x] 2.1 实现scriptgen命令适配器和严格manifest解析
- [x] 2.2 规范化Facade与Job入口及逻辑工具ID
- [x] 2.3 实现MQ Consumer注解扫描
- [x] 2.4 实现状态机与转换结构化扫描
- [x] 2.5 确认V2产物不生成或混入固定shim

## 3. 应用入口

- [x] 3.1 建立单系统源码分析应用服务和异步任务
- [x] 3.2 增加CLI扫描与manifest查询命令
- [x] 3.3 增加FastAPI扫描提交与结果查询接口

## 4. 验证

- [x] 4.1 增加基线、manifest解析、状态机、MQ和失败边界测试
- [x] 4.2 对真实示例系统运行扫描审计并验证 `TradeFacade#createOrder`
- [x] 4.3 运行OpenSpec严格校验、V2与legacy测试
- [x] 4.4 更新架构和开发状态文档
