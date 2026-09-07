# DSFProxy执行与Agent工具设计

## 扫描与真相边界

扫描器交叉读取生产Facade接口、DSF发布XML、环境filter及`dsf_application.properties`，生成带源码证据的`DsfClientProfile`与`DsfOperationDefinition`。动态占位符必须从当前项目QA filter唯一解析；无法解析或来源冲突时保持候选状态，不得猜测。

provider操作进入全局派生索引，但只有调用系统显式确认的`DsfOperationBinding`可以执行。请求只携带操作ID、业务payload、deadline与目录摘要；服务描述只能来自当前扫描绑定目录。

## Worker边界

`qa-dsf-worker`是独立Java 8单请求进程。启动器在0600临时classpath目录生成DSF客户端配置，以被测系统身份连接QA注册中心；Worker使用`DSFProxy.getService(...).action(...)`，返回结构化结果或稳定脱敏错误。日志只保留请求ID、调用系统、操作ID、状态和耗时。

QA Oracle Worker继续只负责MySQL、TiDB、Redis和MQ只读验证。DSF Worker不得复用Oracle操作目录或放宽其READ池门禁。

## 切换与兼容

当前Facade操作目录与执行只使用`dsf_proxy`，能力门禁、扫描投影和Worker均不读取Labrador Token或Facade HTTP网关；scriptgen仍可为扫描兼容输出`facade_raw`，但该工具不进入持久运行目录，也不能成为执行回退。HTTP Job继续独立使用`generated_cli`和现有本地HTTP配置，不得冒充Facade或DSF能力。

Booking.Core自调用与跨Refund.Core调用两个只读金丝雀均成功、且HTTP Job去留明确后，才删除Labrador页面、设置/API和兼容执行器。旧Manifest继续可读但历史Facade脚本不可重放；本地旧配置文件不自动删除。真实金丝雀未获授权前，代码切流与离线验证不得被描述为已完成外部门禁。

## 环境身份

环境目录只投影canonical ID、显示名、系统内显式aliases和安全可用状态，不返回values、connections或凭据。Operation或Case Execution在创建任何执行记录前，只允许精确canonical ID或当前系统唯一alias；未知、重复或跨系统alias直接拒绝，不把`QA1`猜测成`qa`。解析后的canonical ID贯穿DATA、TARGET、ORACLE和CLEANUP，并参与幂等与并发身份。

## QA门禁

真实调用必须由用户逐次确认。TiDB只根据当前系统扫描结果展示；Booking.Core两个TiDB可单独复测显式READ路由，Refund.Core没有TiDB时不得显示或探测Booking资源。createOrder与31个Case不属于只读金丝雀。
