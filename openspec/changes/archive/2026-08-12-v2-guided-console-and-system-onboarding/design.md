# V2引导式控制台与系统接入设计

## Change切换

`dsf-execution-and-oracles`保留未完成任务5.4并记录为`WAITING_QA_INPUT`，不归档。本change作为唯一编码中的核心change；完成并归档后再启动通用知识与Case change。

## 系统注册与本地设置

新系统ID默认取规范化源码路径的basename，允许小写字母、数字、点、横线和下划线。已有调用方仍可显式传入ID；已存在系统的ID不可更新。系统领域真相不保存Token，Token由`LocalSystemSettingsStore`原子写入Git忽略的`.opentest/environments/<system_id>/qa.yaml`，文件权限固定为0600。

注册和更新请求可携带`qa_labrador_token`，但任何响应模型、任务结果和日志均不包含该字段。本地设置API校验请求来源必须是IPv4/IPv6回环地址。已有`${ENV:OPENTEST_QA_LABRADOR_TOKEN}`继续由环境加载器解析；页面首次保存会写为本地明文。

注册成功后提交`facade,job`后台扫描。HTTP响应同时返回系统和`scan_task`，旧调用方只读取`system`仍兼容。扫描失败不回滚系统注册，页面展示任务错误并允许重试。

## 扫描目录

扫描历史直接枚举可重建Manifest，不复制业务真相。目录读取指定Manifest并与Git知识节点、问题和任务状态合并，输出Facade类/方法、Job业务包、MQ Consumer、状态机与流转，以及公共逻辑、外部调用和数据来源知识候选。目录项的知识状态由已发布节点和开放问题确定。

## MQ聚合与状态

静态发现继续保留Producer/Consumer交互事实，但公开资源视图把所有声明按NameServer配置Key聚合为`MqClusterDefinition`。旧MQ资源ID作为`legacy_resource_ids`保留，固定操作目录中的旧资源绑定映射到聚合集群，因此已有Case仍可读取。

连接状态与业务校验状态从现有状态记录投影，不把源码发现当作连接成功。MQ只读探测使用批准Topic查询NameServer路由，不创建Producer/Consumer、不发消息、不写消费位点；若SDK或路由不可用则保持明确阻塞。消息业务效果仍为`EFFECT_ONLY`。

## 控制台

控制台使用工作台、系统配置、扫描结果、测试资源、知识库、回归Case、测试执行、自然语言测试、运行报告九个一级导航。高级JSON仅用于诊断折叠区。所有操作按钮都有可聚焦问号按钮和`role=tooltip`说明用途、前置条件、QA访问、产物和常见阻塞。

本change为知识、Case和自然语言页面建立目录和明确的阶段提示；完整业务功能由后续change接通，不提供会假装成功的占位按钮。

## 兼容与安全

旧`/oracle-operations`保留只读别名，新页面只调用`/validation-capabilities`。旧资源ID、显式系统ID注册和环境变量Token继续兼容。响应不得包含连接地址、账号、远程配置原文、Worker堆栈或Token。
