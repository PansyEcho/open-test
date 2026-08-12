## Why

V2已经能真实发现 `TradeFacade#createOrder`，但入口清单还不能回答Validator、ServiceInvoker、状态变化、港币多乘客规则、DB/Redis/MQ与下游语义。需要把代码证据转换为可检索节点和关系，并把代码无法确定的问题批量交给用户确认。

## What Changes

- 从最近扫描manifest定位入口并追踪实现类、Validator、ServiceInvoker、Builder和关键依赖。
- 生成带源码行号、可信状态和稳定ID的知识节点与关系。
- 将状态机、数据访问、外部调用和公共规则独立成可复用知识。
- 批量生成高影响待确认问题，人工回答与自动区域分离保存。
- 提供最小权限本地Agent Runner作为可选增强，不让Agent输出直接覆盖人工知识。
- 发布后重建SQLite索引，支持由入口沿关系找到深层规则。

## Capabilities

### New Capabilities

- `java-knowledge-tracing`: 从入口向Validator、业务方法、状态与依赖追踪源码证据。
- `knowledge-draft-and-confirmation`: 生成代码知识与批量问题，保存人工回答。
- `agent-runner-boundary`: 以只读源码和受控输出运行可选本地Agent。

### Modified Capabilities

- `git-knowledge-store`: 增加问题、生成批次和确认内容存储。
- `sqlite-knowledge-index`: 发布知识后同步重建节点与关系索引。

## Impact

- 首个纵向切片仅保证 `TradeFacade#createOrder` 深层知识质量，再扩展通用入口。
- 不执行DSF、不生成Case、不引入向量数据库或跨系统关系。
