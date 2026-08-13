# DSF扫描网关与任务反馈修复设计

## 扫描参数

`OpenTestApplication._source_scan_request`是页面、CLI和后台扫描进入scriptgen前的统一策略边界。处理顺序为：

1. 请求显式提供`facade_http_prefix`时保留该值；
2. 未显式提供时读取`.opentest/environments/<system_id>/qa.yaml`中的`qa_gateway_prefix`；
3. 两者均为空时在创建scriptgen子进程前拒绝；
4. Booking.Core未显式提供Job规则时，使用最终Facade前缀派生`/job`规则；
5. 只复制网关字符串，不读取、记录或传递Token。

## 控制台终态

`showTaskProgress`只在`completed`时正常返回；`failed`和`interrupted`读取最终任务错误后抛出异常，由保存或重扫入口统一展示一次失败Toast。调用方只有在任务完成且扫描目录实际加载成功时展示最终成功提示。

已有系统与本地配置不回滚，因为失败发生在后台扫描阶段，保留系统可以让用户修正网关或扫描器后直接重试。

## 兼容与安全

- 现有显式CLI前缀继续优先，不被本地页面设置覆盖。
- 本地设置动态读取，因此无需重启Uvicorn即可修改网关并再次扫描；本次Python代码变更本身仍需重启未启用reload的服务。
- 旧失败工具目录保留为本地诊断，不会成为`latest` Manifest。
