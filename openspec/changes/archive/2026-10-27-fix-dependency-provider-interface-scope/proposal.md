## Why

依赖系统卡片误用了完整操作目录，把该系统调用第三方的外部 DSF 和 MQ 操作混入自身对外接口，导致展示、全开范围和保存校验错误。

## What Changes

- 接口授权目录仅包含该注册系统自身的 Facade 对外接口，数据库能力继续由独立权限控制。
- 默认已选与引用、全部展示、一键全开和保存校验共用该范围；历史误存的外部接口或 MQ 授权不能作为该系统对外接口授权使用。
- 调用方外部 DSF 定义仍按明确关系映射到实际提供方 Facade 授权；不改通用操作目录或系统合并规则。

## Impact

- Affected specs: dependency-construction-permissions
- Affected code: DependencyAccessService、权限回归测试及隔离页面验收输入。
