## Why

Case 编译器无法处理合法 nullable Schema，失败任务又无法修订；知识页仍读取旧长文和人工枚举候选，下游目录误用执行资格过滤发现结果。网页后台运行与 Codex 接续缺少单一执行者交接。

## What Changes

- 修复 nullable 类型校验及原任务恢复，保留请求幂等和修订冲突检查。
- 用独立接口用途、请求和响应字段契约替换知识主视图，修正代码枚举分类。
- 按系统展示调用方已发现的下游及引用接口，支持任务内按需寻找下游其他接口。
- 退役 Labrador HTTP Job 配置、扫描和执行路径，保留 DSF/MQ。
- 网页自动分析结束后，在同任务切换 native，再打开原 Codex 会话答题。

## Capabilities

### New Capabilities
- `generation-knowledge-workflow`: 编译恢复、独立契约、外部接口发现和单执行者交接。

### Modified Capabilities
- `knowledge-target-workspace`: 契约视图和只读代码枚举。
- `guided-system-onboarding`: 无 Labrador 的注册及系统目录。
- `runtime-scanner-settings`: 不再要求 HTTP 网关。
- `interactive-generation-workflows`: 同任务网页到 Codex 接续。
- `codex-knowledge-continuation`: 接续后在原 Codex 会话回答。
- `generalized-knowledge-workflow`: 内部实现仅按需源码分析。

## Impact

沿用现有任务、契约、扫描和知识存储；旧补充输入格式保持可读。增加目标级契约投影、用途/响应补充、下游检索工具及 native 接续 API。生成期间不访问 QA，不修改其他活动变更。
