## Decisions

- 搜索仅过滤本地入口目录，使用页面专属 combobox，不增加组件库。搜索草稿与选中 ID 分离，确认后才触发原有 change 联动；取消恢复原选项。
- 环境读取置于系统确认之后、其他系统数据读取之前；失败由环境区域反馈，不中断其他目录。
- 历史仅缓存 ScanHistoryItem，按系统和文件路径定位、mtime_ns 与 size 比较，新增/变化文件逐个解析并释放 Manifest。缓存有条目与字节上限；latest 独立读取，文件删除时清除摘要。
- 枚举类型判断使用扫描器的精确 kind，字段证据和 Schema 均将其视为标量。字段 Schema 取自完成 required 整理后的请求 Schema，保留模型一致性校验。
- 现存 BLOCKED 输入契约只在内存中重新推导；不覆盖正式知识或历史 Generation，未解决的阻塞继续报错。
- 沿用既有日志上下文及 finally 清理；更新浏览器资源 URL 和页面版本，保护既有未提交改动。

## Verification

验证搜索及键盘操作、选择联动、跨系统隔离、慢历史不阻塞环境；缓存增删改和容量；枚举/集合/必填规则及 BLOCKED 恢复。用真实 createOrder 扫描和隔离 HTTP 服务验证，不执行 QA。OCR delegation 只审查本任务补丁。
