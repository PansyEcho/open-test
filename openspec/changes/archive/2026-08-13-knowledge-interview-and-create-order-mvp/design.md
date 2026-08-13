# 知识访谈与 createOrder MVP 设计

## Change边界

`multi-system-console-reliability-and-reset` 已归档。本 Change 是唯一实施中的核心 Change；`dsf-execution-and-oracles` 继续等待真实QA输入且任务5.4保持未完成。

## 知识访谈与修订

每个系统拥有一份本地草稿态 `KnowledgeInterview`，覆盖系统用途、主要上游、分单系统关系、下游和业务术语。访谈答案本身不自动变成已确认接口事实；应用层根据稳定问题与目标关系计算影响节点，把答案作为 `answer_notes` 注入所有相关草稿并触发确定性重生成。

开放问题统一从知识问题目录读取。回答时先校验问题和影响节点均属于当前系统，再更新问题、关联草稿和影响摘要。用户在知识聊天框提交的反馈先生成 `KnowledgeRevisionPlan`，包含澄清问题、影响节点和当前/建议内容差异；只有问题回答并再次确认后才发布Git知识。Agent输入仍只包含源码证据、已发布知识和用户业务说明，不包含本地Fixture、Token或QA结果。

## 自然语言阻塞预览

预览创建首先匹配业务入口。缺少用户确认的入口知识时返回 `BLOCKED`，携带 `missing_conditions` 和结构化修复动作：前往扫描结果、生成知识、回答问题。该路径不探测资源、不创建Snapshot、不调用DSF或Worker。知识、Fixture和资源能力齐备后才进入现有 `READY → CONFIRMED → EXECUTED` 流程。

## 本地Fixture安全

`CreateOrderMvpFixtureStore` 把完整请求保存在 `.opentest/environments/<system_id>/create-order-mvp.yaml`，写入前拒绝符号链接并以同目录临时文件、`fsync`、原子替换和0600权限发布。读取API只返回 `configured`、请求SHA-256、乘客数量、预期供应商、票机模式和非敏感背景完成状态，不返回Token、请求正文、姓名、证件、电话或连接信息。Snapshot只记录Fixture摘要。

页面把Fixture放在“测试执行 → 测试数据”，自然语言页不展示JSON。完整请求只允许回环接口写入；服务日志、任务结果和异常均不得包含请求正文。

## createOrder MVP 编排

`CreateOrderMvpService`只接受固定Booking.Core系统ID。执行前验证：QA环境、已确认 `TradeFacade#createOrder` 知识、Fixture、当前Snapshot、真实工具及所需校验能力。运行时复制Fixture请求，只替换唯一 `traceId` 和 `bookInfo.serialId`，保留 `OPENTEST` 测试前缀。

步骤固定为：

1. 调用真实 `TradeFacade#createOrder`；
2. 断言响应成功、订单号、交易号和供应商结果；
3. 使用批准操作查询MySQL主库、临时库和Item；
4. 使用批准Redis模板验证待票机集合与票机处理中状态；
5. 仅当Fixture声明异步票机且前后数据库/Redis变化可归因时记录MQ `EFFECT_ONLY`，否则标记 `N/A`；
6. TiDB固定报告 `BLOCKED / READ_POOL_UNAVAILABLE`，不计入MVP硬通过条件；
7. 报告保存测试订单号和人工/QA既有机制清理责任，不执行数据库写清理。

MVP执行复用现有类型化执行器、临时Java Worker和Run证据，但报告只保留白名单业务字段。Fixture未就绪时返回 `BLOCKED` 计划，不创建业务订单。

## API与控制台

新增访谈读取/保存、知识反馈/修订计划、MVP Fixture状态/写入和MVP计划/执行API。所有敏感写接口只接受回环请求。知识页面展示流程、问题红色数量、回答框和反馈框；测试执行页展示Fixture状态和本地填写区。
