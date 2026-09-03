# Tasks

## 1. Contract and server rules

- [x] 1.1 增加PublishedCapabilityRef、TestFact契约、步骤输入/输出和依赖证明模型
- [x] 1.2 增加系统Git SetupFactContract/InputPolicy读取与校验
- [x] 1.3 增加DataSetupRecipe与校验结果模型，Fact Schema只由程序派生

## 2. Validation and storage

- [x] 2.1 按排序多系统事务校验consumer/provider latest、Published和直接SETUP绑定
- [x] 2.2 校验服务器输入策略、Fixture Schema、literal白名单和Fact子字段类型
- [x] 2.3 校验事实契约来源、程序派生Schema、单/多航段及约束冲突
- [x] 2.4 保存二元Published引用与依赖证明，增加只读/提交API且不访问QA
- [x] 2.5 追加依赖/规则不可变版本历史，读取时按历史scan、Published和版本记录重算程序派生证据

## 3. Verification

- [x] 3.1 增加跨系统Published、并发漂移、Candidate/旧能力阻塞和Fact约束测试
- [x] 3.2 增加Fixture/literal业务身份、Fact子路径、类型和依赖删除边界测试
- [x] 3.2a 增加Git篡改、严格标量白名单、前向Fact、规则版本和跨进程锁测试
- [x] 3.3 使用正式退款与Booking原样隔离副本验证Published=0时真实阻塞且零Recipe写入
- [x] 3.4 运行本变更相关测试和OpenSpec检查
- [x] 3.5 使用OCR delegation和同一只读Agent复核实现与测试来源
