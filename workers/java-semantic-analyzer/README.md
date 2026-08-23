# Java Semantic Analyzer

本地、可替换的 JavaParser + Symbol Solver Sidecar。它输出版本化 JSON：方法、调用边、入口复用范围、注解、枚举展示名、模式证据、解析状态与源码引用。JavaParser 类型不会进入 OpenTest Python、知识文件或前端契约。

构建：

```bash
mvn -q -f workers/java-semantic-analyzer/pom.xml test package
```

缺失依赖、动态代理和反射目标会被标为 `partial` / `unresolved`；分析器不会用启发式关系冒充高置信度调用边。
