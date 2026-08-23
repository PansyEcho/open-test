# DSFProxy执行与Agent工具设计

## 扫描与真相边界

扫描器交叉读取生产Facade接口、DSF发布XML、环境filter及`dsf_application.properties`，生成带源码证据的`DsfClientProfile`与`DsfOperationDefinition`。动态占位符必须从当前项目QA filter唯一解析；无法解析或来源冲突时保持候选状态，不得猜测。

provider操作进入全局派生索引，但只有调用系统显式确认的`DsfOperationBinding`可以执行。请求只携带操作ID、业务payload、deadline与目录摘要；服务描述只能来自Snapshot绑定目录。

## Worker边界

`qa-dsf-worker`是独立Java 8单请求进程。启动器在0600临时classpath目录生成DSF客户端配置，以被测系统身份连接QA注册中心；Worker使用`DSFProxy.getService(...).action(...)`，返回结构化结果或稳定脱敏错误。日志只保留请求ID、调用系统、操作ID、状态和耗时。

QA Oracle Worker继续只负责MySQL、TiDB、Redis和MQ只读验证。DSF Worker不得复用Oracle操作目录或放宽其READ池门禁。

## 切换与兼容

内部先并存`generated_cli`与`dsf_proxy`用于离线测试和两个只读金丝雀。Booking.Core自调用与跨Refund.Core调用均成功后，新Snapshot只生成`dsf_proxy`工具并删除Labrador设置/API/UI与执行器。旧Manifest和Snapshot继续可读，但`generated_cli`历史运行被稳定拒绝为不可重放；本地旧配置文件不自动删除。

## QA门禁

真实调用必须由用户逐次确认。TiDB只根据当前系统扫描结果展示；Booking.Core两个TiDB可单独复测显式READ路由，Refund.Core没有TiDB时不得显示或探测Booking资源。createOrder与31个Case不属于只读金丝雀。
