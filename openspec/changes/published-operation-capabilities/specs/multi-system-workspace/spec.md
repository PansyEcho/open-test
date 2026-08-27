# multi-system-workspace Delta

## MODIFIED Requirements

### Requirement: 同一知识仓库支持多个彼此隔离的系统

系统 SHALL 允许注册、更新和读取多个系统，并按稳定系统 ID 隔离知识、扫描、Candidate、Published、Case、资源与报告；直接依赖绑定只允许跨系统发现Candidate，不允许跨系统发布或写入provider注册表。

#### Scenario: consumer发现provider Candidate后发布

- **WHEN** consumer通过直接绑定搜索到provider Candidate
- **THEN** consumer路由不得发布该Candidate，调用方必须使用provider系统路由并只写provider的Published注册表
