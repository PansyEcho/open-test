## MODIFIED Requirements

### Requirement: 同一知识仓库支持多个彼此隔离的系统

系统 SHALL 按稳定系统ID隔离各系统资产，从DSF/MQ扫描自动汇总只读方向关系；新任务只发现自身及分别沿上下游最多两层可达的已接入项目，不使用人工绑定、操作/用途白名单或项目间环境映射。跨系统执行使用被调用项目自身qa/uat配置，发布仍写入资产所属项目。

#### Scenario: 更新一个系统

- **WHEN** 用户编辑已注册系统的名称或源码路径
- **THEN** 注册表只替换对应ID的记录，其他系统定义和资产保持不变
- **AND** 源码路径变化后该系统的Candidate范围阻塞到新扫描完成

#### Scenario: 新增系统

- **WHEN** 用户处于新增模式并提交另一个有效源码目录
- **THEN** 系统创建基于目录名的独立ID，而不是覆盖当前系统

#### Scenario: 扫描形成关系
- **WHEN** 扫描确认A调用B或生产B消费的消息
- **THEN** A展示B为下游且B展示A为上游，关系由同一源码证据产生

#### Scenario: 最多两层且不绕旁支
- **WHEN** 当前系统分别搜索上下游依赖
- **THEN** 使用独立已访问集合进行两层BFS，排除自己和重复项，第三层及改变方向才能到达的旁支不返回

#### Scenario: consumer发现provider Candidate后发布
- **WHEN** consumer通过扫描关系发现provider Candidate
- **THEN** 发布使用provider路由并只写provider资产，关系不会改变资产归属

#### Scenario: 执行跨系统数据步骤
- **WHEN** 已接入目标项目和固定操作可用且本次任务触发执行
- **THEN** 使用目标项目同名逻辑qa/uat Profile，不要求额外关系授权
- **AND** 缺配置或未接入在业务调用前报告具体缺口
