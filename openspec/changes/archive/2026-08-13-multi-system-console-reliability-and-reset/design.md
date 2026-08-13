# 多系统控制台可靠性与混合数据重置设计

## Change 与数据边界

`dsf-execution-and-oracles` 保持 `WAITING_QA_INPUT`，任务 5.4 未完成且不归档。本 Change 是唯一编码中的核心 Change。

系统注册表是公司级路由清单，每次更新按稳定 `system_id` 合并，不得重写其他系统。知识、扫描、Case、资源状态、本地设置、任务、Snapshot 和报告继续携带 `system_id`；应用服务在每个读写边界校验归属，一期仍禁止跨系统引用。

## 可恢复归档

归档由控制面生成不可变 `archive_id`，并使用同一文件系统内的原子重命名移动资产：

- Git 可提交系统目录移入 `open-test-knowledge/archives/<archive_id>/knowledge/`；
- 本地 `.opentest` 中与该系统有关的环境、扫描、任务、报告、草稿、资源状态和 Snapshot 移入 `.opentest/archives/<archive_id>/local/`；
- 根清单记录原系统定义、错误源码路径、归档原因、每个文件的相对路径、大小和 SHA-256；
- 先复制/移动到临时归档目录并验证摘要，成功后才从活动注册表移除；失败时回滚，不能留下半归档状态；
- 恢复前验证摘要和目标冲突，恢复后重新构建 SQLite 派生索引。

当前混合数据按上述协议归档；不会使用不可恢复删除。归档目录支持页面查看和恢复，敏感本地资产保持 Git 忽略且文件权限收紧为 `0600`。

## 动态 scriptgen 设置

运行设置保存在仓库根 `.opentest/settings.yaml`，文件原子写入且权限 `0600`。解析优先级为：

1. `OPENTEST_SCRIPTGEN_PYTHONPATH` 环境变量；
2. 本地设置 `scriptgen_pythonpath`；
3. 当前 Python 环境已安装的 `cli_anything.scriptgen` 模块。

每次扫描前重新解析，不缓存 Uvicorn 启动时结果。就绪检查验证目录、`cli_anything/scriptgen/__main__.py` 和隔离子进程模块启动能力。诊断只返回来源、稳定状态与脱敏修复提示，不返回进程环境。配置无效时，API 返回字段化错误并且不创建后台任务。

## 本地系统设置与 Curl

DSF 注册要求系统名称、有效源码目录、Labrador QA Token 和 `qa_gateway_prefix`。Token 与网关前缀保存在 `.opentest/environments/<system_id>/qa.yaml`；共享系统定义不包含二者。Token 仅回环接口可完整读取，Curl API 只返回接口后缀、请求模板和不含 Token 的结构化片段，由浏览器从本地设置组合并复制。OpenTest 不执行 Curl。

## 排他任务

全局任务门禁为跨线程、跨进程文件锁加持久化活动记录。扫描、知识批量生成、资源探测、回归执行等冲突长任务提交前原子占用；活动记录包含任务 ID、系统 ID、阶段和无敏感摘要。任务完成或异常时在 `finally` 释放。进程死亡时通过既有 owner heartbeat 恢复，不让陈旧记录永久锁死控制台。公开状态 API 供页面刷新后恢复全屏 Loading。

## 控制台和扫描目录

系统配置是列表页，新建和编辑使用不同状态；右上角选择器保存非敏感当前系统 ID。系统切换先清空当前页缓存、选中节点、抽屉和表单，再并行加载目标系统数据。导航折叠状态保存在浏览器本地设置。

扫描目录把 Facade 展示为 `类别 → 类 → 方法`，叶子只显示方法名；Job、状态机和公共候选采用同类层次。所有层级默认折叠，父层折叠时展示状态统计，展开后由叶子展示状态。筛选支持大类和详细状态，每个知识目标可跳转到知识页并选中目标。

## 资源投影

资源主表以当前成功扫描 Manifest 的源码摘要为边界，只展示本次源码实际发现且适配当前系统的资源。旧摘要状态放入高级历史。MQ 按 NameServer 配置 Key 聚合；Producer、Consumer、Topic、Group、Tag 和源码证据只在详情中展示。资源状态同时绑定源码摘要、操作目录摘要和 Worker 摘要，漂移时标记过期。

Booking.Core Worker 只接受新系统 ID `travelsystem.java.dsf.supplychain.booking.core` 与同 ID 操作目录，同时固定 `appName=travelsystem.java.dsf.supplychain.booking.core`、`environment=qa`。其他系统无专用适配器时明确显示“不支持结果校验”，不得调用 Booking.Core Worker。
