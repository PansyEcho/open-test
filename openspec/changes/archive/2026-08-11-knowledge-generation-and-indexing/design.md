## Context

目标入口经过 `TradeFacadeImpl#createOrder` 与公共execute代理，动态按 `ApiServiceEnum.CREATE_ORDER` 选择 `CreateOrderValidator` 和 `CreateOrderServiceInvoker`。后者调用 `OrderBuilder`、订单持久化、分单、状态机和事件；港币价格规则又深入到每名乘客的报价查询与fallback。单纯目录或全文搜索无法稳定表达这种深层关系。

## Goals / Non-Goals

**Goals:**

- 让入口查询能沿结构化关系到达深层规则与源码证据。
- 代码事实和人工业务口径使用不同状态，不把推断伪装成确认。
- 高影响问题按批次输出，避免逐行“grill”用户。
- 自动更新不覆盖人工回答和补充。

**Non-Goals:**

- 不承诺完整Java语义分析；一期针对目标系统的Spring/ApiService约定。
- 不让本地Agent直接修改业务源码或执行网络命令。
- 不生成跨系统知识或测试变体。

## Decisions

### 证据优先的两层分析

确定性分析器先按类型、注解、调用和关键条件提取节点。可选Agent只接收限定源码文件和结构化任务，用于总结候选结论；其输出状态默认 `inferred`，必须经过模型校验和用户确认才能成为业务口径。

### 稳定节点与关系ID

入口节点使用完整 `Facade#method`，公共逻辑使用类或方法符号，业务规则使用入口域与规则slug。关系明确区分calls、reads、writes、transitions和depends_on。每个节点保留system_id、scan_id和SourceReference。

### 批量问题

只为影响硬断言、场景可构造性或数据清理的未知结论生成问题。一次生成一个YAML批次，问题包含影响节点和high/medium/low；回答写在自动区域之外，并可将相关节点升级为 `user_confirmed`。

### 发布顺序

分析结果先通过Pydantic与同系统关系校验，再写节点、关系和问题，最后重建SQLite。索引失败不改变Markdown/YAML真相，下一次可重建恢复。

## Risks / Trade-offs

- [正则追踪可能漏调用] → 保存warning和未解析符号，关键切片用真实源码验收。
- [Agent幻觉] → 只读、最小环境、结构化输出、默认推断态且需源码证据。
- [问题过多] → 仅批量输出高影响问题，低影响推断保留状态但不打断用户。
- [规则重复] → 以稳定规则ID去重，多个入口通过关系复用公共节点。

## Migration Plan

1. 为最近真实扫描的createOrder生成知识。
2. 验证能检索Validator、ServiceInvoker、状态流转和港币逐乘客报价规则。
3. 保存待确认问题并重建SQLite。
4. 后续按相同模型扩展全部入口。

## Open Questions

QA中的实际港币报价来源优先级和缺失报价是否允许成功，需要用户确认后决定Case硬断言。
