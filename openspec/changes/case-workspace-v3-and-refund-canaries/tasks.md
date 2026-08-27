# Tasks

## 1. V3 execution

- [x] 1.1 增加类型化步骤证据、执行请求和本地Attempt存储
- [x] 1.2 按Setup/Fault/Action/Oracle/Cleanup顺序执行Published能力
- [x] 1.3 Cleanup和Fault撤销在失败路径仍执行并决定最终状态
- [x] 1.4 增加Variant执行及Attempt列表API

## 2. Real entry pipeline

- [x] 2.1 增加从真实知识入口派生的通用流水线投影
- [ ] 2.2 完成真实Facade入口的Setup、Action、Oracle和Cleanup闭环
- [x] 2.3 仅在真实扫描和知识存在时展示MQ入口

## 3. Workspace

- [x] 3.1 页面改为真实目录、Scenario/Variant/Attempt、规则、阻塞和证据展示
- [x] 3.2 更新静态资源版本和旧页面写操作门禁
- [x] 3.3 通过运行中的HTTP服务验收V3页面和API

## 4. Verification

- [x] 4.1 增加模型、服务、API和页面契约测试
- [x] 4.2 运行相关测试、完整测试和OpenSpec严格校验
- [x] 4.3 使用OCR delegation复核本变更差异
