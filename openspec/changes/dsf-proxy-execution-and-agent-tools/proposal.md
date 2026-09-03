# Change: DSFProxy执行与Agent工具目录

## Why

现有Facade执行依赖Labrador脚本、网关地址和Token，无法复用被测系统自身的DSF身份，也不能把其他已扫描系统的Facade安全开放给Agent。执行描述还停留在脚本路径，缺少可审计的DSF服务、版本和动作契约。

## What Changes

- 增加独立Java 8 DSF Worker，通过`DSFProxy`执行固定目录中的Facade操作。
- 从被测项目发布配置和Facade源码发现DSF客户端Profile与provider操作。
- 增加项目级操作确认及调用系统到目标操作的绑定，支持本系统自调用和跨系统调用。
- 将DSF Profile、操作目录和Worker身份绑定到当前不可变扫描代际；HTTP Job继续使用原有工具。
- 两个只读金丝雀均通过后移除Labrador页面、设置与执行通道；历史扫描与操作目录保持只读。

## Scope

一期只允许QA环境和用户确认的固定操作。真实业务标识保存在本地0600 Fixture中；本Change不执行写操作或回归Case。

## Non-Goals

- 不把HTTP Job伪装成DSF操作。
- 不允许Agent提交任意gsName、service、version或action。
- 不修改只读QA Oracle Worker的安全契约。
- 不在未通过只读金丝雀时删除Labrador兼容实现。
