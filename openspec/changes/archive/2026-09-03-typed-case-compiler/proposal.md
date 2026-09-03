# Change: 服务端可信的分型Case编译器

## Why

Pairwise不能承担边界、分支可达、顺序、故障和副作用覆盖。旧编译请求还能提交完整Manifest、执行图、Setup/Cleanup ID、内联Oracle和任意`base_inputs`，会绕过前四阶段的程序冻结、Published注册和Fact来源边界。

## What Changes

- 公共编译请求只接受`entry_id`；程序从latest scan、Program分析、Semantic Draft和规则重新冻结覆盖清单。
- 只通过阶段3 Published服务、阶段4 Recipe服务和服务器Git编译规则解析Action、Setup与Oracle模板；调用方不能选择或内联正式资产。
- 分别编译Factor、Boundary、Decision、Sequence、Effect和Requirement；Pairwise只处理Factor，Fault本阶段固定阻塞。
- 增加`SetupFact → ActionInput → ActionResult → ActionFact → Oracle/Cleanup`类型事实链和业务身份来源证明。
- 增加每个Variant的覆盖证明、每个义务的终态和稳定Scenario模板身份；本阶段不访问QA、不创建Attempt。
