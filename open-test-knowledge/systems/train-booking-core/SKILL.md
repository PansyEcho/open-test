---
name: train-booking-core
description: 查询和维护火车票预订核心DSF系统的Facade、Job、MQ、状态机、业务规则、数据依赖和测试场景。当用户询问TradeFacade#createOrder、订单流程、港币多乘客场景、Case生成、需求评审或回归影响时使用。
---

# Train Booking Core

这是一期唯一注册系统的业务知识包。知识结论必须能追溯到源码、用户确认或QA环境观察；不得混入固定离线shim的行为。

## 检索顺序

1. 读取 `source.yaml` 确认源码路径、分支、commit和dirty摘要。
2. 优先在 `references/facades/` 按完整符号定位DSF入口，例如 `TradeFacade#createOrder`。
3. 沿 `relations.yaml` 展开Validator、ServiceInvoker、业务方法、状态流转、DB/Redis/MQ和下游调用。
4. 公共规则在 `references/shared/`，状态机在 `references/state-machine/`，数据知识在 `references/data/`。
5. 生成或评审测试时读取 `cases/` 的场景、变体和覆盖目标；执行前核对Snapshot版本绑定。
6. 若高影响结论无法由代码确定，读取或新增 `questions/` 中的批量待确认问题。

## 回答规则

- 清楚区分请求字段的结构含义、代码校验规则和仍待确认的业务含义。
- 引用源码证据时给出文件、符号、行号和扫描基线；dirty基线还应给出摘要。
- `code_verified`只表示代码路径可证，不代表线上业务口径已经人工确认。
- 节点状态为 `conflict` 或 `stale` 时先提示风险，不把它作为硬断言来源。
- 生成港币多乘客场景时，成人、儿童、币种、报价完整性和支付校验开关是独立约束；不得通过裸笛卡尔积制造无业务意义组合。
- QA配置和密钥仅从本地环境读取，不写入本知识包。

## 变更维护

- 自动扫描只更新自动区域，并保留人工补充。
- 源码变化后先比较基线和受影响符号，再更新相关节点、关系、覆盖目标和变体。
- 更新完成后重建SQLite索引；SQLite不得成为知识写入入口。
- 一期不建立跨系统关系。外部依赖只记录为当前系统的 `external_call` 节点。
