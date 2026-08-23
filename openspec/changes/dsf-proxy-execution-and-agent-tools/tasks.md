## 1. 规范与领域契约

- [x] 1.1 建立proposal、design、tasks和delta specs
- [x] 1.2 增加DSF Profile、操作定义、调用绑定与Snapshot摘要模型

## 2. 扫描与存储

- [x] 2.1 从项目发布XML、Facade和QA filter发现DSF Profile与provider操作
- [x] 2.2 实现项目级确认、跨系统派生索引和旧Manifest兼容读取

## 3. Worker与执行

- [x] 3.1 实现独立Java 8 DSF Worker和0600文件协议
- [x] 3.2 实现Python启动器、目录摘要校验、日志上下文和脱敏响应
- [ ] 3.3 将Facade工具切换为`dsf_proxy`并保持HTTP Job不变

## 4. 接口与页面

- [x] 4.1 增加Profile、操作候选、确认、Fixture摘要和执行API
- [ ] 4.2 增加操作确认页面，并在金丝雀通过后移除Labrador输入

## 5. 验证

- [x] 5.1 完成Worker、扫描、越界、兼容和脱敏离线测试
- [ ] 5.2 经用户确认执行两个只读DSF金丝雀
- [x] 5.3 运行完整测试、浏览器验收和OCR delegation审查
- [x] 5.4 更新状态文档；保持原任务5.4和31个Case阻塞
