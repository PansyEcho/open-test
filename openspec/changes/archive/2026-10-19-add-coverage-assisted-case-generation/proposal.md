# Change: 增加可选的覆盖率辅助 Case 生成

## 当前状态

**实现、两次真实 QA 闭环和 OCR delegation 独立审查已完成；清理及严格校验已通过，随本 change 归档；证据见 tasks。** 生成 Case 的覆盖辅助任务使用可选 source_revision：填写 commit/tag，留空解析 qa 分支最新提交，固定为完整 commit 并复用已有源码 pin/scan。本期不要求自动识别当前部署版本或部署升级映射。手选或默认版本均不保证 QA 正在运行该版本；每轮仍核对实际构建制品和 class ID，缺制品或不匹配只跳过增强，基础 Case 继续。非增强的历史生成路径保持既有版本行为。

### 2026-10-19 准入核查结果

- 已只读核对公司 `command.sh` 和 FTP：WAR 与配套源码按应用、环境、构建版本和 commit 归档。归档应用名为 `iflightchainsaas.java.dsf.refund.core`，与 OpenTest 系统 ID 不同；脚本允许同路径重新上传，路径本身不构成不可变保证。
- 用户更正退款天网 appId 为 `3265415`。以 `appIds=["3265415"]`、原 token Header 查询参考 QA 地址成功；响应 appId=3265415、appUk=iflightchainsaas.java.dsf.refund.core、env=qa，最新五条记录 IP 均为 `10.175.78.54` 且时间倒序。本次结果不证明所有分页排序、时间边界或副本数量。
- appId 和 token 均保存在本机受 Git 忽略的系统级 system.yaml，权限 0600；系统页面、私有 GET/PUT 和运行时读取已实现，GET 只返回 appId/token_configured，Token 不回显。
- 本次用户选择 `7b962925`，完整 commit 为 `7b962925db34b181f66e39a9262356585a8fcc03`，对应归档版本 `-8`。
- 已下载该 commit 的构建 WAR（144472167 字节）及源码包（1867366 字节），两者均与 FTP SIZE 一致，下载前后 MDTM 未变。WAR 包含 7 个 `refundcore-*-1.0.52-emailTopic-SNAPSHOT.jar`；源码包包含 1954 个文件。
- 对 `10.175.78.54:6300` 的只读 JaCoCo dump 已成功，CLI 0.8.5 解析到 573 条类记录，其中 328 条位于退款业务包且有命中；不再用无业务交集的旧 dump 验证本次部署。
- 328 条退款业务类中，300 条与 WAR 字节码 class ID 一致、不匹配为 0；其余 28 条为运行期生成类，未比较，不计为匹配。匹配类中 299 条进入报告，1 条 synthetic 类由 JaCoCo 过滤，已用 CLI 自带 CRC64 核对。
- 已用 7 个完整业务 JAR 和同归档源码生成 HTML/XML 报告，分析 713 个含可执行代码的类；累计行覆盖率 17.87%、分支覆盖率 3.82%。这是共享实例累计快照，不是某一接口或本次 Case 的覆盖率；已加载交集匹配也不独立证明所有未加载类或下一次部署的版本身份。
- 用户已明确允许退款系统 QA agent reset，这是该系统本次 QA 测量的许可依据，不代表已独立调查所有消费者，也不扩大到 UAT。上述准入取样本身只做只读 dump，不构成自动测量闭环。
- 本次构建样本取得、可比较业务类匹配及 reset 许可满足实施准入；之后已完成两次真实自动闭环。第二次增强版 2 个 Variant 均 PASSED，接口范围行快照由 3/16 变为 13/16；3 项处置漏答仍保存 UNRESOLVED，不作因果归因。严格 OpenSpec 校验只验证文档结构，不能代替这些功能验收。

## Why

现有基础 Case 可能遗漏代码流程，需要在保持基础生成与真实业务验证可用的情况下，用实际覆盖数据提供一次有界补充，并保留逐项理由、执行结果和成本供人工评估。

## What Changes

- 新增独立 capability `coverage-assisted-case-generation`：仅对符合条件的 QA 自动验证执行，采集 JaCoCo 单实例快照并最多补充一轮 Case。
- 覆盖辅助生成增加可选 source_revision 输入；空值默认 qa，首次解析后固定完整 commit，发布重试、continue 和增强沿用已有 pin/scan，不漂移到更新后的分支或 tag。
- 实例发现通过可替换接口接入，本期实现最新有效天网日志查询；系统页面维护 appId 和 token，统一保存于该系统本机配置并跨环境复用，缺依赖只跳过增强。
- 复用现有执行、TaskRecord、线程池、维护回调和 MySQL 聚合存储；增加准确的自动执行绑定、事务派发、专属任务同步及严格的退出恢复规则。
- 去重并限制代码缺口，独立复核忽略理由，由生成模型最终裁决；不把建议变成业务断言或发布门禁。
- 展示后台增强状态、单实例限制和已有后继任务；保留轻量历史及按配置保留的最近一轮原始报告。
- 系统页面提供启用开关和保留粒度，工作台高级设置提供 JaCoCo 工具路径及审查模型；本机 QA 可选择实际本地构建包／源码／commit 或固定 FTP 版本及凭据环境变量引用。

## Impact

- 新增 delta spec：`specs/coverage-assisted-case-generation/spec.md`；实施按本 change 推进，验收后再归档到现行规范。
- 实现范围：覆盖辅助生成的版本选择、配置模型及系统设置、实例发现和 JaCoCo 模块、Case 发布与后台执行协调、专属增强恢复、类型化存储和查询、前端状态与报告。
- 不新增物理表、列、索引、调度器、持久队列或 Case 执行 owner 字段；不修改 `DataCapabilityService._recover_execution`。
- 原始报告的 gzip result 保存 exec 和恢复所需 FrozenCoverageArtifact，包括本机固定定位或 FTP 路径及凭据环境变量名称，不保存真实凭据；仅原采集工作台后端可读，前端和模型只读取工作流投影。
- 不交付 MySQL／Redis 操作识别、业务状态或参数组合穷尽、全副本／请求归因、手动覆盖重测、普通手动或历史 Case 的中断修复；不提高现有 100 个 Variant 上限。

## Design Sources

- [需求定稿](../../../../docs/discussions/case-generation-requirements-review.md)
- [流程定稿](../../../../docs/discussions/coverage-assisted-case-generation.md)
- [数据定稿](../../../../docs/discussions/coverage-assisted-case-generation-data-design.md)

本 change 同时纳入用户最新约束：专属 TaskRecord 的执行完成同步必须位于 `_finish_execution` 的 `finally`；同步不得把仍有增强后续步骤的总流程提前结束。派发失败和无法执行 finally 的进程退出分别由派发边界、恢复流程处理。
