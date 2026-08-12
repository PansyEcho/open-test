## Why

现有MVP已经验证了扫描、知识草稿、Case和回归报告的产品流程，但核心实现集中在单个大类，知识与Case包含固定示例，并且缺少可审计的Git知识真相源。现在需要建立独立V2核心，让后续单系统DSF闭环、HTTP和Web执行器能够在稳定契约上迭代。

## What Changes

- 在同一仓库新增独立的 `opentest` V2包，legacy `ai_test_platform` 保持可运行但不再承载新能力。
- 引入Pydantic领域模型、统一错误契约、日志上下文和本地任务状态模型。
- 建立以Markdown/YAML为真相源的Git知识仓库，首期只注册一个系统。
- 建立可删除重建的SQLite FTS5索引，支持节点、关系、别名和全文查询。
- 增加FastAPI与CLI共享的应用装配入口，为后续能力提供稳定边界。
- 不迁移现有MVP数据，不引入向量数据库，不实现跨系统场景。

## Capabilities

### New Capabilities

- `v2-runtime-foundation`: V2领域模型、错误契约、日志上下文、本地任务和应用装配。
- `git-knowledge-store`: 单系统Git知识目录、自动/人工内容边界及版本元数据。
- `sqlite-knowledge-index`: 从知识文件重建的SQLite FTS5节点与关系索引。

### Modified Capabilities

无。

## Impact

- 新增Python依赖FastAPI、Pydantic和Uvicorn，并保留现有pytest验证链路。
- 新增 `opentest` 包、`open-test-knowledge` 知识目录和 `/api/v2` 基础接口。
- legacy API、数据目录和现有43个测试不做破坏性修改。
