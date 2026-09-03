# Change: 跨系统数据前置Recipe与可信测试事实

## Why

创建退票单等Case不能把“先获得出票成功订单”硬编码进Case生成器，也不能让Fixture、literal或退款能力伪造上游业务资源。需要由可复用Recipe组合少量Published原子能力，并让程序通过服务器维护的事实契约与输入来源策略验证Fact来源。

## What Changes

- 增加`PublishedCapabilityRef(system_id, capability_id)`，Recipe归属被测consumer，但每个步骤按引用所属系统解析Published能力。
- 跨系统步骤只允许使用consumer到provider的直接依赖，且用途必须含`SETUP`；上游事实额外要求`role=UPSTREAM`。
- 增加系统Git维护的Setup事实契约和输入来源策略。AI只能引用契约/策略，不能在Recipe中自行降低来源要求。
- Fact Schema由程序从Published输出路径派生；Recipe不重复提交或改写Fact Schema。
- 未被输入策略明确允许的literal或Fixture失败关闭；业务身份输入只能来自前序Fact，Fixture使用不含值的闭合Schema验证路径和类型。
- 在按系统ID排序的多系统事务中重新验证consumer latest、依赖、provider latest、Published和Recipe身份，再只向consumer Git写入不可变Recipe。
- 提供Recipe提交、阻塞原因、列表和详情API；本变更不执行QA调用，运行时重新校验和逐步物化留给阶段8。
