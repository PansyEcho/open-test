## 1. 执行领域与配置

- [x] 1.1 增加执行请求、Oracle、环境配置和Snapshot领域模型
- [x] 1.2 实现本地QA配置读取、环境引用和敏感字段隔离
- [x] 1.3 实现Snapshot摘要、持久化和读取

## 2. 类型化执行内核

- [x] 2.1 实现inputs/steps/qa变量绑定和缺失错误
- [x] 2.2 实现JSON输出解析、路径断言与结构化diff
- [x] 2.3 实现run/step证据持久化和失败边界

## 3. DSF与Oracle

- [x] 3.1 实现真实scriptgen逻辑工具解析和DsfExecutor
- [x] 3.2 实现DSF、MySQL、Redis与MQ Oracle扩展边界
- [x] 3.3 实现有截止时间的异步轮询和最后观察证据
- [x] 3.4 增加CLI和FastAPI Snapshot、执行与报告入口

## 4. 安全Worker与资源可观测性

- [x] 4.1 增加MySQL、TiDB、Redis与MQ资源领域模型、源码发现和状态存储
- [x] 4.2 实现Java 8 QA Worker、固定操作目录、READ池和QA身份门禁
- [x] 4.3 用Worker适配器替代booking.core的Python直连MySQL/Redis路径
- [x] 4.4 将Worker Jar与Oracle目录摘要绑定Snapshot
- [x] 4.5 增加资源列表、探测API和控制台状态面板
- [x] 4.6 增加回归Suite批量运行和全局Job预检、一次性确认Token

## 5. 验证

- [x] 5.1 增加工具越界、shim、变量、JSON、断言、轮询和Snapshot测试
- [x] 5.2 使用本地假工具完成createOrder变体执行与Oracle闭环
- [x] 5.3 增加Worker策略、资源状态、API、批量执行和Job门禁测试
- [ ] 5.4 在Fixture就绪后执行真实DSF、MySQL、TiDB、Redis与MQ效果金丝雀
- [x] 5.5 运行strict校验、V2与legacy测试及OCR delegation审查
- [x] 5.6 更新架构、QA配置、资源状态和开发进度文档
