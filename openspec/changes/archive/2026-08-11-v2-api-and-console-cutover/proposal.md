# Change: V2 FastAPI与本地控制台切换

## Why

V2应用服务已经覆盖系统、扫描、知识、Case、Snapshot和执行，但HTTP依赖尚未完成运行验证，现有控制台仍只调用legacy手写路由。用户需要一个不依赖legacy Platform大类的完整入口来观察和操作单系统闭环。

## What Changes

- 补齐 `/api/v2` 的Case编辑、Snapshot、执行和报告契约。
- 由FastAPI托管新的V2本地控制台，复用现有信息架构但直接调用V2 API。
- 增加API契约测试、静态资源测试和CLI/API一致性验证。
- 保留legacy服务器和43个测试，不在本change删除旧代码或迁移旧数据。
- 文档明确V2启动、QA阻塞和后续legacy删除条件。

## Scope

一期控制台服务唯一注册的DSF系统，不加入浏览器Web Executor或跨系统界面。

## Non-Goals

- 不删除 `ai_test_platform`。
- 不迁移legacy JSON数据。
- 不提供多人权限和中央服务。
