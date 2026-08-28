## REMOVED Requirements

### Requirement: 回归Case必须经过场景矩阵人工确认

**Reason:** 当前V3写流程已经由正式资产直接确定性生成不可变Scenario和Variant，旧矩阵确认写入口已退役；继续保留该要求会与真实API和本Change新增要求冲突。

**Migration:** 旧矩阵和由其生成的历史Case保持只读；新的生成请求直接进入正式资产编译，QA执行仍由用户另行显式触发。

## ADDED Requirements

### Requirement: 回归Case由正式资产确定性生成

系统 SHALL 由用户显式发起、基于当前正式知识和已发布资产直接生成不可变Scenario与Variant，不再要求先创建并人工确认旧场景矩阵；访问QA仍须由用户另行显式触发。

#### Scenario: 从正式资产生成Case
- **WHEN** 用户为latest scan真实入口发起Case生成
- **THEN** 系统编译覆盖义务、Setup、Action、Oracle和Finalization并写入不可变Generation，且不访问QA

#### Scenario: 程序资产足以生成Case
- **WHEN** 当前正式知识、Published能力和Recipe已能确定性编译READY Generation
- **THEN** 系统直接返回Scenario和Variant，不创建或启动Codex任务

#### Scenario: 剩余缺口没有合法AI输入
- **WHEN** 缺口来自未完整扫描、未确认知识或所选路径仍不完整的Candidate Schema
- **THEN** 系统返回具体待补充或阻塞，不得反复调用Codex猜测程序事实

#### Scenario: 离线环境仍可编译Case
- **WHEN** Published能力已冻结程序要求的本地绑定路径，但当前QA Token为空或内网不可达
- **THEN** 发布和Generation仍只按正式代码与资产完成，不读取或访问QA环境；用户显式执行时才在Attempt预检返回环境阻塞

#### Scenario: 显式执行生成结果
- **WHEN** 用户明确执行一个Ready Variant
- **THEN** 系统才访问QA并创建独立Attempt

#### Scenario: 执行前缺少本地绑定
- **WHEN** 用户执行Variant但某个冻结Published能力的本地绑定在目标环境缺失或为空
- **THEN** Attempt在写入RUNNING和OperationExecution之前以PREFLIGHT BLOCKED结束，且QA调用数为零

## MODIFIED Requirements

### Requirement: 缺失条件不得被猜测或绿色通过

系统 SHALL 在正式前置事实、Published能力、Recipe、Oracle、故障触发或Finalization不足时显示一个具体业务阻塞，不得生成假Ready或伪造PASSED。

#### Scenario: 缺少有状态实体Producer
- **WHEN** 入口需要某状态实体且没有可验证的正式Producer Recipe
- **THEN** Generation保持Blocked并说明缺少查询或创建方式，且不创建Attempt

### Requirement: 人工Case资产不可被全量生成覆盖

系统 SHALL 只追加或替换同入口的系统生成资产，并保持人工Case、用户编辑Case、旧矩阵、历史Generation和Run只读不变。

#### Scenario: 重复生成同一冻结输入
- **WHEN** 用户对相同源码、知识、规则和Published资产重复生成
- **THEN** 系统得到确定性的义务与Variant且不修改人工或历史资产
