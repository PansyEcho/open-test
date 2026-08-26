## ADDED Requirements

### Requirement: 知识页使用目录、正文和问题三栏工作台

控制台 SHALL 在桌面端同时展示知识对象目录、当前对象已确定知识和待确认问题。统一问题只在右栏回答，中栏不得提供背景、候选、修订或草稿的直接编辑、确认和发布入口。

#### Scenario: 选择接口知识

- **WHEN** 用户从左栏选择一个Facade方法
- **THEN** 中栏展示接口说明、输入输出、流程、规则、异常、Oracle和相关术语
- **AND** 中栏只显示已发布知识和代码证据，未确认草稿仅形成右栏问题
- **AND** 右栏可在未填写、已填写和全部问题之间切换，并继续按当前对象筛选

#### Scenario: 背景完成后生成当前对象知识

- **WHEN** 用户已填写四项核心背景、确认“背景与术语已完善”、明确选择可用Codex或Claude Code并选择一个接口或公共逻辑
- **THEN** 流程条步骤1显示完成，步骤2显示待处理数量、当前Agent和带Agent名称的“生成当前对象知识”
- **AND** 页面不得展示“生成全部”入口，旧批量请求包含多个目标时必须在创建任务前明确拒绝
- **AND** 提交前确认摘要展示Agent、当前对象、目标数量1、注册源码根内只读边界和可能产生API费用，未确认不得创建任务
- **AND** 请求必须携带明确Agent，后端不得自行选择或切换到另一个Agent
- **AND** 当前目标依次执行确定性追踪、指定Agent只读解释、严格校验、按来源发布和检查点保存
- **AND** Agent启动前必须由代码沿已解析调用边扫描当前接口可达的公共业务方法、精确状态流转及Actor公共逻辑，并按当前scan的知识状态确定需要生成的依赖节点
- **AND** 公开`target_ids`只包含用户选择的接口，`candidate_node_ids`必须包含主接口及缺失、过期、失败、有开放问题或子节点不完整的确定性依赖；当前scan下完整的`INFERRED / USER_CONFIRMED`依赖只建立关系并跳过重写
- **AND** Agent只能解释并覆盖系统给定的全部`candidate_node_ids`，不得自行扫描、新增、删除或替换公共依赖，主接口与依赖在同一task、handoff、thread、batch和scan中一次校验并原子发布
- **AND** 代码可以证明的节点直接以`CODE_VERIFIED`发布，Agent代码解释以`INFERRED`发布，只有用户后续确认才标为`USER_CONFIRMED`
- **AND** 监控注解中的同名字符串、更早调用点或参数注解数组不得截断真实方法体，方法/构造器声明不得冒充调用或副作用，源码引用指向真实声明行
- **AND** 合法入口仅能证明方法存在时发布最小`CODE_VERIFIED`事实并标记“仅代码事实”，不得固定生成业务口径问题或生成伪共享节点
- **AND** 指定Agent失败时不得调用另一Agent，应保存确定性事实并标记“仅代码事实 / Agent失败”
- **AND** Agent失败但代码事实已保存时任务终态必须为`partial`，并分别展示`agent_failed_count`、`deterministic_failed_count`和合计`failed_count`，不得显示“completed / 失败0”
- **AND** 只有确定性追踪也失败时才标记“生成失败”
- **AND** 任务失败或取消时Loading可以关闭，但页面必须保留常驻摘要、已有事件和明确重试入口

#### Scenario: 未选择或所选Agent不可用

- **WHEN** 全局知识生成Agent为空，或用户选择的Codex或Claude Code当前不可用
- **THEN** 当前对象生成不得提交
- **AND** 页面说明需要选择或修复的具体Agent，不得将另一Agent作为默认兜底

#### Scenario: Codex客户端接管与重新生成

- **WHEN** 用户选择Codex并点击初次生成或重新生成当前唯一目标
- **THEN** 请求携带`interaction_mode=codex_client`、`intent`和稳定`attempt_id`，创建同一知识实体下的handoff、草稿批次、等待任务和持久Codex thread
- **AND** App Server只创建、命名和注入无turn持久历史；页面先通过`codex://threads/<id>`打开同一聊天，再由同用户本机桌面IPC向当前owner请求一次follower start-turn
- **AND** OpenTest只使用`thread/read(includeTurns=true)`轮询，不得调用`thread/resume`、`turn/start`或保持后台生成进程；同一thread已有活动turn或已处理turn时重复请求返回`already_started`
- **AND** `/knowledge/client-handoffs/{handoff_id}/turns`幂等返回`started / already_started / manual_required`，桌面IPC缺失、版本不兼容或未接管时只提示在原任务手动发送开始消息，不得退回OpenTest writer
- **AND** 点击本身授权同一handoff/thread连续分析、补读、修正和重提候选，不得为每次校验错误再次询问；不得创建第二handoff/thread、扩展目标或切换Agent
- **AND** 全仓库任一时刻最多存在一个可继续交流、自动补全、等待回答或等待确认的Codex知识聊天；同一attempt重复提交返回同一任务与thread，其他系统或目标的并发创建必须被拒绝
- **AND** 已生成、失败、部分完成和过期目标都提供重新生成；新候选确认前旧知识继续有效，拒绝、放弃或发布失败不得覆盖旧知识
- **AND** 客户端插件只允许经回环接口读取handoff、调用三个受控源码工具和提交候选；OpenTest可以规范化真实已读区间内可唯一证明的Java方法简称和Mapper节点引用，但缺少真实`read_source`区间、目标入口不匹配或Facade主链不完整时不得回写
- **AND** 机器完整度缺口必须在原任务自动补全，完整候选通过全部门禁后直接发布；只有具有源码证据和明确影响范围的高影响业务问题才可使用`needs_input`
- **AND** OpenTest页面只展示接管状态、源码轨迹、确认结果与最终知识，Codex增量聊天留在客户端；Claude Code仍在OpenTest页面流式展示

#### Scenario: 历史客户端状态原地恢复

- **WHEN** 服务读取历史`waiting_for_completion`，或页面打开已有活动Codex turn的旧任务
- **THEN** 系统保留原task、handoff、thread、batch和scan，把历史补全状态原地迁回机器补全，并等待活动turn结束后只读协调
- **AND** 不得取消已有生成内容、关闭非OpenTest进程、创建第二线程或取得会话writer

#### Scenario: 四步流程与背景后续编辑

- **WHEN** 用户首次确认四项核心背景后又显式保存系统定位、主流程、上下游或业务术语修改
- **THEN** 步骤1继续保持已完成并显示首次完成时间，不自动调用Agent或产生费用
- **AND** 旧知识仍可浏览，受影响目标标记为已过期，步骤2显示需要更新的数量和唯一下一步操作
- **AND** 系统级背景变化默认影响全部知识，术语变化优先只影响`affected_target_ids`，无法定位时影响全部

#### Scenario: 重复扫描与源码变化

- **WHEN** 新扫描与知识批次扫描的源码路径、commit、分支、dirty状态、dirty摘要和分析器版本完全一致
- **THEN** 已生成知识不得仅因`scan_id`变化而标记过期
- **AND** 任一源码基线字段变化、历史扫描无法验证、知识节点显式STALE或背景影响目标时，相关知识仍标记过期

#### Scenario: 查看全部问题与当前对象问题

- **WHEN** 用户选择普通知识目标
- **THEN** 右栏立即切换为当前对象且只渲染关联问题
- **AND** 左栏固定入口显示“全部待确认问题（N）”，点击后中栏展示周期概览、右栏展示全部问题
- **AND** 全部问题每次最多增加20张卡，未打开全部问题时不得创建问题全集卡片

#### Scenario: 轻量详情与Loading

- **WHEN** 用户首次打开知识库、切换目标或执行查询、刷新、保存、确认、发布与重试
- **THEN** 对应目录、中栏、右栏或按钮在请求发出后100毫秒内展示骨架或忙碌状态并防止重复操作
- **AND** 切换目标必须在同一帧清除旧接口正文并显示当前目标名骨架，取消旧GET并以选择代次拒绝迟到响应
- **AND** 页面使用`aria-busy`和状态播报，失败时只展示当前新目标的常驻摘要、Toast和重试入口，不得恢复其他接口正文
- **AND** 普通目标轻量详情不得重复返回问题全集或完整上下文，也不得重复执行全量问题与上下文查询

#### Scenario: 每个接口只恢复自己的生成尝试

- **WHEN** 同一系统的多个接口先后存在生成、失败、客户端等待或完成任务
- **THEN** Agent卡、任务、事件、诊断、handoff和最终知识按当前`system_id + target_id + attempt_id`选择
- **AND** 工作流可以返回目标级`generation_attempts`，但页面禁止用系统级最新任务回落到没有匹配attempt的接口
- **AND** 快速切换时旧接口响应、事件或finally不得覆盖新目标的Loading、任务卡或正文

#### Scenario: 流式展示、刷新和服务重启恢复生成任务

- **WHEN** 指定Agent正在分析、页面SSE断线、页面刷新或OpenTest服务重启
- **THEN** AI分析面板按事件序号展示供应商公开推理摘要、Agent消息、状态和用量，不得展示隐藏思维链、提示词、认证信息或供应商原始事件
- **AND** 没有新消息时仍展示进程心跳、累计耗时、最后活动时间、实际Agent、当前目标和会话ID
- **AND** SSE使用最后事件序号自动续传且保留轮询降级，断线或刷新不得创建新的Agent调用
- **AND** 刷新后的工作流快照必须恢复同一活动任务、目标、实际Agent和阻塞原因；任务运行或等待回答时生成按钮保持禁用，重复POST返回冲突且不得启动Runner
- **AND** Agent执行不设固定分析超时且标准输入关闭，只有用户主动取消才终止仍存活的工作进程
- **AND** 服务重启后工作进程存活时接管原事件流，已有最终输出时继续校验发布，进程消失时标记中断并要求再次确认费用
- **AND** 用户显式点击诊断入口后应恢复本次精确Prompt、公开事件、受控源码访问轨迹、最终结构化输出、会话ID和手动恢复命令，但不得自动续跑或展示隐藏思维链、认证信息与供应商原始事件

#### Scenario: Agent受控扫描完整业务调用路径

- **WHEN** 当前Facade入口通过`execute`、服务枚举、代理或注解动态分发到实际业务实现
- **THEN** Runner必须保持Shell、原生文件工具、网络、浏览器、用户MCP和写能力关闭，仅开放注册源码根内的列举、搜索与读取工具
- **AND** 受控工具拒绝绝对路径、上级路径、逐级符号链接、QA、Fixture、测试和构建目录及其文件名/分隔符/驼峰/大写缩写变体，搜索使用线性字面量且疑似认证赋值只返回脱敏占位
- **AND** Agent必须从入口继续定位Validator、Invoker或Provider，进入核心Service及DAO/Mapper或远程边界，并结合已保存业务背景解释请求转换、主流程、分支、副作用、返回组装与异常
- **AND** 严格输出必须提供从1开始的`trace_steps`，公开Facade接口或对应同名实现均可作为首个entry，并将可选Invoker、核心Service和首个数据访问或远程边界分别绑定到顶层源码引用
- **AND** 核心路径到首个数据或远程边界为止必须前向连通；边界后的Service或Invoker返回组装可以继续展示，不得仅因角色回退或最后一步不是边界而拒绝
- **AND** Facade只到接口、Invoker或Service，使用未经证明的`no_downstream`，或任意引用行不在本次`read_source`区间时不得标记完整生成；校验通过的完整路径引用必须追加到发布知识证据

#### Scenario: 严格Agent输出Schema在本地预检

- **WHEN** OpenTest准备启动Codex或Claude Code单目标知识分析
- **THEN** Agent信封、摘要数组、问题和最小源码引用的全部字段都必须显式必填，对象必须设置`additionalProperties: false`
- **AND** 摘要必须使用`[{node_id, summary}]`数组，源码引用只包含必填`path`、`symbol`和可空`line`，执行路径步骤必须包含顺序、角色、源码引用和摘要，不得使用动态Map
- **AND** 根对象、对象闭合性、全字段必填和不支持组合关键字必须在供应商进程启动前递归预检
- **AND** 预检失败不得创建Agent运行目录、启动供应商进程、调用另一Agent或产生API费用

#### Scenario: Agent需要用户回答后续接原会话

- **WHEN** Agent只能在用户确认高影响业务疑点后完成当前对象分析
- **THEN** 系统先发布`CODE_VERIFIED`事实、暂缓未完成推断、把任务标记`WAITING_FOR_INPUT`并在当前对象右栏实时显示问题
- **AND** Codex客户端任务卡展示问题标题、说明、选项和“在Codex中回答”，用户在原thread直接回复后继续提交最终候选
- **AND** 回答和最终提交复用原task、handoff、thread、batch和scan，不创建下一尝试或要求普通完整度确认
- **AND** `completed`候选不得残留开放问题；通过全部门禁后自动发布，Agent解释保持`INFERRED`且不得伪装为`USER_CONFIRMED`

#### Scenario: 按填写状态切换问题

- **WHEN** 当前周期有7项非空暂存答案和22项未填写问题
- **THEN** 默认“未填写”Tab显示22，“已填写”显示7，“全部问题”显示29
- **AND** “暂不确定”计入已填写，保存答案后问题立即从未填写迁移到已填写
- **AND** Tab、范围、优先级和分类筛选不得改变整轮29项完整性门禁

#### Scenario: 暂存并完成问题周期

- **WHEN** 用户在右栏逐题保存答案
- **THEN** 顶部展示已保存数与周期总数，每张卡展示证据、提问原因、影响和保存状态
- **AND** 底部固定完成按钮在全部问题保存前保持禁用并列出缺答数量
- **AND** 对象、优先级和分类筛选只改变卡片显示，不改变整轮完成范围

#### Scenario: 周期正在重新分析

- **WHEN** 用户完成全部答案并启动本地重算
- **THEN** 右栏展示绑定扫描、任务身份和阶段进度
- **AND** 失败时展示安全错误、保留答案并提供重试入口

#### Scenario: 选择业务背景

- **WHEN** 用户选择业务背景
- **THEN** 中栏只读展示人工确认背景、`CONFIRMED`术语/外部应用和独立标记的`CODE_VERIFIED`事实
- **AND** OPEN、NEEDS_REVIEW和UNRESOLVED候选只在右栏出现
- **AND** 左栏分别包含业务术语、业务枚举和外部应用分组，业务枚举以业务名称为主标题、Java符号为次级标识
- **AND** 缺少可信类注释的枚举以Java枚举名和“代码默认（可修订）”来源进入目录，不生成右栏维护问题
- **AND** 背景页的术语与外部应用摘要不得混入业务枚举长列表

#### Scenario: 从接口查看相关业务枚举并返回

- **WHEN** 用户从业务背景、接口或公共逻辑点击直接相关的业务枚举、术语或外部应用
- **THEN** 中栏展示业务名称、代码标识、逐值含义、人工备注、来源证据和影响目标
- **AND** 页面提供返回原业务对象的入口，并恢复原聊天作用域、右栏对象筛选和移动抽屉状态
- **AND** 系统或扫描周期变化后清空返回栈，迟到响应不得恢复旧系统视图

#### Scenario: 显式发送知识修订聊天

- **WHEN** 用户在当前背景、候选、接口或公共逻辑作用域点击“发送并分析”
- **THEN** 系统保存消息并只在此时运行本地只读Agent
- **AND** 严格校验后的精确提案进入右栏“确认发布 / 暂不确定”问题，中栏不直接发布
- **AND** Agent失败或输出非法时消息保留为BLOCKED并提供重试，不生成猜测知识
- **AND** 系统切换或知识对象切换后的迟到提交、轮询和刷新响应不得清空输入或覆盖当前页面

#### Scenario: 恢复聊天历史

- **WHEN** 页面刷新、服务重启或系统归档恢复
- **THEN** 中栏恢复当前系统隔离的消息、分析状态和关联提案
- **AND** 本地会话目录权限为0700、文件为0600且拒绝符号链接
- **AND** 页面持续提示不得输入Token、真实订单号、HT/TX、merchant、乘客身份或Fixture正文

#### Scenario: 移动端查看工作台

- **WHEN** 视口为390×844
- **THEN** 目录与问题栏可通过抽屉访问
- **AND** 页面无横向溢出、双重内容滚动或控制台错误

### Requirement: 页面配置Codex速度与业务Prompt

现有本机运行设置 SHALL 提供Sol或Luna的Low/Medium选择，新配置、省略字段和无有效本机配置时 SHALL 默认`gpt-5.6-luna / low`，并 SHALL 提供一份全局业务Prompt模板、变量说明、默认恢复和当前目标完整Prompt预览。固定安全、工具、目标身份、输出Schema和补全协议 SHALL 不可编辑。

#### Scenario: 新配置不改变活动任务

- **WHEN** 用户保存新的模型档位或Prompt模板且已有Codex知识聊天未结束
- **THEN** 活动任务继续使用创建时保存的模型、档位、模板版本和最终Prompt快照
- **AND** 新配置只作用于下一次聊天

#### Scenario: 展示隔离调用契约

- **WHEN** 当前接口知识具有`invocation_contract`
- **THEN** 中栏在业务知识正文之后以默认折叠的独立区域展示契约
- **AND** 不改变原三栏知识阅读、问题或修订流程

### Requirement: 活动任务与知识生成历史分离

系统 SHALL 只在右栏任务区域展示仍在运行或等待处理的Codex知识任务，并 SHALL 把完成、失败、取消、中断和部分完成记录移入本地归档。归档记录 SHALL 继续按任务ID可读，并在对应知识详情中提供状态、时间、安全错误和Codex聊天跳转。

#### Scenario: 终态任务离开右栏

- **WHEN** Codex知识任务进入任一终态
- **THEN** 任务记录移动到archive且不再出现在普通任务列表
- **AND** 对应知识详情仍能展示历史并打开原Codex聊天

#### Scenario: 服务启动清理既有终态记录

- **WHEN** 服务启动时活动任务目录包含历史终态Codex handoff
- **THEN** 系统原样归档这些JSON且不删除，不影响运行中或等待处理任务

### Requirement: 已发布知识一键生成并执行回归Case

系统 SHALL 按知识目录展示具有真实执行入口的已发布Facade、Job和MQ知识。用户点击生成后 SHALL 在一个任务中完成只读场景矩阵、多个Case和执行步骤，不要求人工确认矩阵。全量生成 SHALL 只替换同入口旧系统生成资产，并 SHALL 保留人工Case、用户Case、其他入口Case和Run。

#### Scenario: 已生成知识直接产生多个Case

- **WHEN** 当前扫描入口具有`GENERATED`或`CONFIRMED`知识及一个以上确定性覆盖点
- **THEN** 系统规范化扫描入口ID，生成只读矩阵并立即编译全部Case和步骤
- **AND** 不创建矩阵确认按钮、确认任务或等待确认状态

#### Scenario: 同入口全量替换

- **WHEN** 同一入口已有系统生成Case并成功完成新一轮全量生成
- **THEN** 系统在新批次校验通过后替换该入口旧Generation、CoverageTarget、Scenario和Variant
- **AND** 人工Case、用户Case、其他入口Case和历史Run保持不变

#### Scenario: 缺少执行能力

- **WHEN** 某覆盖点缺少本地Fixture、固定Oracle、业务断言或必要清理责任
- **THEN** 系统仍保存对应Case但将其变体标为blocked并显示具体缺口
- **AND** 不得访问QA或把空断言Case标记为可执行

#### Scenario: 批量执行当前入口

- **WHEN** 用户对生成记录显式确认QA执行
- **THEN** 系统绑定当前Snapshot并以独立Run执行全部就绪变体，跳过并汇总blocked变体
- **AND** 一个变体失败不得阻止后续变体执行，最终返回通过、失败和阻塞数量
