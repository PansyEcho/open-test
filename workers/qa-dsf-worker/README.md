# QA DSFProxy Worker

独立 Java 8 单请求进程。它只接受 Python 生成的 0600 请求文件和固定操作目录，通过源码发现并经用户确认的客户端 Profile 调用 `DSFProxy`。Worker 不接受临时 `gsName/service/version/action`，也不记录 payload、响应、注册地址或 SDK 异常原文。

构建：

```bash
mvn -q -f workers/qa-dsf-worker/pom.xml test package
```

真实 QA 执行必须由 OpenTest 回环 API 发起，并继续受 Profile、操作绑定和只读金丝雀门禁限制。
