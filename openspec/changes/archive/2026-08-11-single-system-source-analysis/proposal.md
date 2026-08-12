## Why

V2基础已经能够保存系统和知识，但还没有可信的源码基线与真实入口清单。legacy扫描流程会在scriptgen结果旁注入固定离线shim，无法作为真实DSF执行和知识生成的输入。需要先把真实scriptgen扫描、状态机解析和版本绑定收敛成独立适配器。

## What Changes

- 捕获注册系统的Git分支、commit、dirty状态和dirty摘要。
- 调用真实scriptgen生成Facade与Job工具，只接收生成清单，不创建固定 `platform/*` shim。
- 将Facade、Job、MQ Consumer和状态机转换为Pydantic结构化入口与关系数据。
- 把扫描产物保存在可删除的 `.opentest/scans` 和 `.opentest/tools`，将源码基线写回Git知识包的 `source.yaml`。
- 提供应用服务、CLI和FastAPI异步扫描任务入口。

## Capabilities

### New Capabilities

- `source-baseline-capture`: 绑定一次分析使用的源码分支、commit和未提交差异摘要。
- `scriptgen-source-scan`: 使用真实scriptgen发现DSF Facade、Job及逻辑工具。
- `java-structure-scan`: 结构化发现MQ Consumer和 `@State` 状态机转换。

### Modified Capabilities

- `v2-runtime-foundation`: 增加扫描任务提交、查询和产物定位。

## Impact

- 新增Git、scriptgen和Java结构扫描适配器，不导入legacy `Platform`。
- 本change只分析一期注册系统，不生成业务知识正文、不执行DSF工具。
- scriptgen路径通过环境或显式配置传入，不把公司本机绝对路径固化为领域规则。
