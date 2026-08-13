# natural-language-blocked-guidance Specification

## Purpose
TBD - created by archiving change knowledge-interview-and-create-order-mvp. Update Purpose after archive.
## Requirements
### Requirement: 未确认知识产生可操作的阻塞预览

系统 SHALL 在自然语言请求匹配到入口但缺少已确认知识时返回 `BLOCKED` 预览、缺失入口和结构化修复动作，不得抛裸异常或访问QA。

#### Scenario: createOrder知识尚未确认
- **WHEN** 用户描述创建订单但 `TradeFacade#createOrder` 知识未确认
- **THEN** 页面展示前往扫描结果、生成知识和回答问题入口，且不会探测资源或创建订单

