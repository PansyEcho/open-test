# Design

AI可先搜索Candidate并推动所需原子操作发布，再提交Recipe。程序只处理结构化步骤图。每个步骤引用`PublishedCapabilityRef(system_id, capability_id)`；Recipe属于被测consumer入口，跨系统Published仍保存在provider注册表，不能复制到consumer。

## 多系统一致性

发布服务先收集consumer和全部provider系统ID，再按稳定排序一次性持有全部系统锁。锁内重新读取consumer latest、直接依赖绑定、各provider latest、V2 Published注册表、Setup规则和既有Recipe ID，完成全部校验后只写consumer Recipe。任何单系统写路径嵌套在已持有的多系统锁中时只能复用已持有范围，不能再扩张锁集合。

跨系统步骤要求直接`SystemDependencyBinding`，`consumer_system_id`等于Recipe owner、`provider_system_id`等于能力引用系统、`purposes`包含`SETUP`。不允许反向或传递授权。同系统步骤不要求依赖绑定。每次绑定新增或替换先追加不可变`binding_revision_id`历史快照，再切换current；Recipe proof引用该历史版本并保存binding ID、consumer/provider、role和`SETUP`用途。读取历史时从快照重建proof，不能仅信任Recipe内部字段。阶段8执行前仍重新验证当前绑定、provider latest和Published，绑定删除或角色变化后旧Recipe不得继续执行。

## 服务器事实契约

系统Git的`rules/setup-contracts.yaml`由程序读取，不随Recipe提交。它包含：

- `SetupFactContractDefinition`：稳定`fact_contract_id`、所需来源策略、必备字段路径/类型、业务身份路径及必需约束；
- `SetupInputPolicy`：精确二元Published引用、逻辑输入根、允许来源、业务身份标记和允许落Git的安全literal枚举/布尔/边界值。

`fact_name`只是Recipe内实例名。`ticketed-order/v1`规则要求`UPSTREAM_PUBLISHED_OUTPUT`、业务订单身份、出票状态和航段数组；Recipe无法通过改名或把策略降为普通Published输出来绕过。`UPSTREAM_PUBLISHED_OUTPUT`要求产出步骤属于不同provider系统，且直接绑定同时满足`role=UPSTREAM`和`purpose=SETUP`。程序不按`fact_name`或Java方法名硬编码。

Fact Schema由程序从Published `output_fact_schema`的精确`output_path`派生并保存，提交方不得重复提供。约束必须引用真实Fact路径；`cardinality`只用于数组，`eq/in`的值按字段Schema校验，互相矛盾的约束阻塞。业务身份路径不得使用`eq/in`持久化具体资源值。

`fact_contract_id`是版本身份：规则文件允许新增新版本，但既有ID不得删除或原地改写来源、字段或约束语义。每次规则写入先保存不可变`rule_revision_id`快照；Recipe引用发布时规则版本，因此后续合法撤销input policy不会抹掉历史，阶段8再使用current policy判断实时执行权限。`fact_name`只允许不含`.`的实例标识，保证`fact_name.child.path`只有一种解析方式。literal与约束白名单同时比较JSON标量类型和值，`true`不得与`1`、`false`不得与`0`混同。

Git Recipe仍是不可信输入。读取目录或单条Recipe时，程序先按`entry_source_scan_id`读取精确历史scan并验证Entry，再校验步骤和Fact关系，从不可变binding/rule历史重建dependency proof与输入授权，并从冻结Published输出重新派生Fact Schema。篡改程序派生字段、注入Entry或手写自洽proof的资产不能被API返回为“已验证Recipe”。历史复核不读取current dependency、current input policy或provider latest，因此授权撤销和源码漂移不会抹掉历史；实时执行授权仍由阶段8重新验证。

## 输入来源

每个步骤输入根都必须有服务器`SetupInputPolicy`，未分类输入失败关闭：

- `fact`：业务身份唯一允许来源；路径必须指向更早步骤已经声明的Fact子字段，Schema必须可赋给目标输入；
- `fixture`：只有策略显式允许时可用。Recipe提交闭合、shape-only且不含值的`fixture_schema`，程序验证路径和类型；运行时仍须验证实际值；
- `literal`：只有策略显式允许且值属于服务器维护的安全白名单时可用，并按Published输入Schema校验。凭据、订单号、退款单号、乘客身份等不得进入Recipe Git。

单航段与多航段是同一事实契约下的两个Recipe/约束版本，不依赖自然语言猜测，也不能合并覆盖彼此。

## 阶段边界

阶段4只发布不可变Recipe契约，不调用QA、不物化Fact。它验证后续能够按步骤即时物化：每个Fact来自一个已发布步骤，后续Fact输入只能向后引用。真正调用能力、即时验证输出和把Fact送入Action在阶段8实现。

真实退款与Booking验收从正式registered/latest、依赖、本地配置和Git知识构造原样隔离副本。当前两系统Published均为0，因此真实Recipe必须返回`BLOCKED_UNPUBLISHED_CAPABILITY`且不得写正式或隔离Recipe；通用无业务名夹具只验证模型成功路径，不能替代该真实fail-closed验收。
