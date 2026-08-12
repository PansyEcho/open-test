## Context

legacy MVP使用Python标准库HTTP服务和单个 `Platform` 大类管理扫描、知识、Case与执行，数据分散在每个项目工作区的JSON文件中。V2需要在不破坏legacy测试的前提下建立独立核心，并为后续长时间运行的扫描、Agent和执行任务提供稳定契约。

## Goals / Non-Goals

**Goals:**

- 建立不依赖Web框架的类型化领域与应用边界。
- 将Git中的Markdown/YAML作为知识真相源。
- 使用可删除重建的SQLite FTS5索引完成本地查询。
- 为HTTP与CLI入口提供统一日志上下文和任务状态。
- 允许后续扫描、场景和执行能力通过适配器接入。

**Non-Goals:**

- 不迁移legacy数据，不删除legacy入口。
- 不构建跨系统知识，不引入向量数据库。
- 本change不实现完整Java业务追踪、Case生成或真实DSF执行。

## Decisions

### 同仓库新增独立V2包

新增 `opentest` 包，V2不得导入legacy `Platform`。可复用逻辑通过小型适配器重新实现或提取，避免旧数据模型渗透。新开仓库会丢失现有测试和扫描资产，直接改大类则会继续放大耦合，因此均不采用。

### Pydantic模型与FastAPI边界分离

领域数据使用Pydantic v2校验，应用服务接收领域对象。FastAPI仅在API层负责请求、响应和异常映射，CLI调用同一服务。这样未来Web和Agent入口不会复制业务逻辑。

### Git文件是真相源

知识节点使用带YAML frontmatter的Markdown保存，系统与源码基线使用YAML保存。人工内容放在自动区域标记之外；生成器只能替换 `kb:auto-start/end` 范围。

### SQLite是派生索引

索引文件位于知识仓库 `.opentest/index.sqlite`，表包括节点、关系、别名、源码引用和FTS5正文。重建过程先创建临时数据库，再以原子替换方式发布，避免失败时破坏可用索引。

### 本地任务与日志上下文

长任务由进程内线程池运行，状态以JSON文件持久化，进程重启后运行中任务标记为中断。API/CLI入口通过 `contextvars` 绑定 `trace_id`、`filter1` 和 `filter2`，上下文管理器在异常路径也执行清理。

## Risks / Trade-offs

- [FastAPI增加运行依赖] → 在 `pyproject.toml` 明确版本范围，领域和CLI测试不依赖Web进程。
- [YAML手工编辑可能破坏格式] → 读取时执行Pydantic校验，写入使用安全序列化。
- [SQLite FTS5在极少数Python构建中不可用] → 启动时检测并给出明确错误，保留精确ID文件查询作为降级路径。
- [进程内任务不适合多人高并发] → 一期仅支持本地单用户；任务接口保持可替换，后续可接外部队列。
- [legacy与V2并存增加认知负担] → `/api/v2`、独立包和状态文档明确边界，legacy删除另立change。

## Migration Plan

1. 新增V2包、知识仓库和基础API，不修改legacy行为。
2. 保持legacy完整测试通过，同时增加V2测试。
3. 后续change逐项接入扫描、知识、Case和执行。
4. V2纵向闭环稳定后切换前端，legacy删除另立change。

回滚时删除V2入口与本地知识目录即可，legacy数据和API不受影响。

## Open Questions

无。真实QA连接类型与密钥引用在执行change中按环境配置确定。
