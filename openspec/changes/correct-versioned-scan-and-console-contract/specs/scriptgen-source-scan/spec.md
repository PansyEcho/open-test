## MODIFIED Requirements

### Requirement: 真实scriptgen是可执行工具唯一来源

系统 SHALL 调用配置的真实scriptgen读取Facade和Job结构，只根据仍受支持的Job tool manifest建立可执行逻辑工具，不得添加固定离线shim。Facade正式执行由DSF提供；scriptgen为旧Facade HTTP传输输出的描述符只用于核对结构入口身份，不得进入工具目录或作为执行回退，其因缺少旧网关而不可执行不得阻断源码扫描。

#### Scenario: 成功扫描Facade和Job

- **WHEN** scriptgen返回有效scan manifest与tool manifest
- **THEN** 每个入口保留请求响应类型、源码位置和source_id
- **AND** 每个仍受支持的Job工具保留逻辑ID与已就绪生成脚本路径
- **AND** Facade入口不携带旧HTTP工具或脚本路径

#### Scenario: 旧Facade HTTP描述符没有默认网关

- **WHEN** scriptgen成功发现Facade结构，但其`facade_raw`描述符因无法构造旧HTTP `default_url`而标记为不可执行且不生成脚本
- **THEN** 系统仍校验该描述符的身份、类型、相对路径和与Facade结构的一一映射并完成源码扫描
- **AND** 不发布或执行该描述符，不把它作为DSF失败时的回退
- **AND** 缺少Facade path等非网关结构错误仍阻断扫描

#### Scenario: scriptgen不可用

- **WHEN** 配置路径不存在、命令失败或manifest无效
- **THEN** 扫描任务失败并给出精简诊断，不生成伪造工具

#### Scenario: 仍受支持的Job工具不可执行

- **WHEN** Job tool manifest状态不是`ready`或对应脚本不存在
- **THEN** 扫描任务失败且不得把该Job入口发布为可执行

#### Scenario: 入口与工具数量核对

- **WHEN** 扫描完成
- **THEN** scan manifest入口与对应类型的tool manifest描述符一一对应
- **AND** 可执行工具集合只包含已就绪Job工具且不包含`platform/*`
