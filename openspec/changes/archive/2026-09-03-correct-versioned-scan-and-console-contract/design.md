# 版本化扫描与控制台契约修正设计

## Decisions

### 以当前可执行路径为规格真相

Git系统扫描通过`capture_revision`将用户选择的revision解析为完整commit，再由`materialize_revision`生成托管快照。扫描期间及之后的working tree变更不属于该代际，因此Git基线固定为`dirty=false`；只有非Git目录继续使用内容摘要和执行前漂移比较。

### 区分revision与branch

`revision`保存原始branch、tag、commit或默认HEAD。当前兼容模型会把任何显式revision同时写入`branch`展示字段，因此tag或commit值并不能证明真实branch归属。规格只承诺原始revision和完整commit，把`branch`定义为非权威展示提示，不声明“resolved branch”或commit所属branch。

### 使用能力对应的版本化API

控制台不是一个只能访问V2的独立客户端。系统、扫描、知识与资源继续使用V2，Hybrid Case使用V3，Case Template使用V4；所有路径仍禁止回退到legacy `/api/projects`。

### 合并归档覆盖后的跨系统要求

OpenSpec按同名Requirement整体替换，后归档的Published delta只保留了一个场景。最终Requirement需要同时保留系统更新、新增、直接候选发现、禁止传递或反向发现，以及consumer不得发布provider Candidate五类约束。

### 删除已经完成阶段的临时失败关闭

Candidate阶段用于保护未重建能力的两个Requirement在Published、Setup、Fault、Cleanup与V3能力交付后已失效。删除它们不会放宽Candidate只读隔离；实际发布和执行仍受各自正式规格约束。

### 按后缀选择环境filter

资源扫描不是只识别一个固定文件名。显式环境读取源码根内安全的`*.<environment>`文件，auto优先`*.qa`并在缺失时回退`*.test`，再与无后缀`dsf_application.properties`模板合并。实际选中的后缀冻结到scan和DSF profile，当前DSF、数据库与MQ Operation不重新猜测环境；尚无scan-bound执行适配器的资源不能借此宣称已支持。

### 不把发送能力声明为Observer

V4当前可从授权数据库Operation派生只读MySQL Runtime Function。Redis和MQ只有在目录中存在独立、已授权、只读观察函数时才可编译；MQ发送Operation或空目录不能冒充Observer，必须明确BLOCKED。

## Verification

- 对修正Change运行严格校验。
- 对全部主规格和活动Change运行严格校验，确认不存在结构错误。
- 独立审查本次AGENTS与OpenSpec差异，并修复High/Medium问题。
