# V4控制台迟到错误隔离设计

## Decision

每次handoff加载在发起时捕获`v4CaseRequestGeneration`和当前视图身份。成功和异常路径在写入DOM、Toast、轮询状态或共享JSON前执行同一代次校验；用户请求Generation历史时推进代次，使所有旧handoff结果失效。失效异常只结束旧Promise，不清空当前Generation JSON，也不显示与当前视图无关的刷新失败。

## Verification

- 用可控Promise分别模拟旧handoff GET迟到成功和迟到拒绝。
- 验证用户切换Generation历史后，两种旧结果都不能改写状态、错误区或JSON。
- 更新浏览器静态资源版本，并通过运行中的HTTP页面验证新版本资源实际加载。
