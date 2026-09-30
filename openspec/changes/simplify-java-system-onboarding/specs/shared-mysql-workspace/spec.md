## ADDED Requirements
### Requirement: MySQL为唯一生产运行存储
系统 SHALL 要求有效MySQL配置与连接，缺少配置或连接失败时明确报错，不切换文件或SQLite运行分支。历史格式读取仅在离线迁移恢复工具保留。

#### Scenario: 本地重复文件清理后重启
- **WHEN** 按身份、版本、内容和引用验证共享库后删除重复历史文件与可恢复缓存
- **THEN** 重启从MySQL恢复；本机配置、源码绑定及local_only历史归档和恢复内容保持不变
