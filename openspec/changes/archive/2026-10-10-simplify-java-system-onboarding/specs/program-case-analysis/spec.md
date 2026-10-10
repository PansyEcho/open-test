## REMOVED Requirements
### Requirement: 程序Case分析必须由独立scan绑定资产提供
**Reason**: 真实扫描中该资产几乎只包含框架噪声（补单14个接口产生330项“待语义分区”和38项调用顺序，业务分支条件为空），并使补单查询Case因27项覆盖遗漏无法发布。用户决定整体删除程序覆盖分析，Case只按真实断言判定。
**Migration**: 扫描不再生成或保存ProgramCaseAnalysisCatalog；历史scan包和Generation中的旧覆盖字段只被忽略，不再读取或补建。

### Requirement: 扫描bundle必须完整校验后原子发布
**Reason**: 扫描发布不再包含程序覆盖目录，发布边界只校验Manifest、接口目录与契约。
**Migration**: latest仍只在Manifest与接口发布成功后推进，见scriptgen-source-scan的“程序解析与可靠结果发布”。

### Requirement: 语法事实不足时不得提升为核心业务义务
**Reason**: 不再从语法事实编译覆盖义务。
**Migration**: 无；分支和边界由生成Case的Agent读取固定源码自行判断。

### Requirement: Semantic Draft必须覆盖完整缺口分母且不能删除程序义务
**Reason**: 没有程序缺口分母后，Semantic Draft失去用途。
**Migration**: Case提交不再包含semantic_draft；旧草稿中的该字段被忽略。

### Requirement: 冻结清单只能由服务端可信资产组装
**Reason**: 不再存在覆盖清单。
**Migration**: 无。

### Requirement: 框架适配必须保留操作身份和静态能力边界
**Reason**: 该要求只服务于副作用覆盖义务；删除覆盖分析后没有消费者。
**Migration**: Java语义分析器保留现有提取能力，但扫描不再把副作用登记为必须观察的义务。
