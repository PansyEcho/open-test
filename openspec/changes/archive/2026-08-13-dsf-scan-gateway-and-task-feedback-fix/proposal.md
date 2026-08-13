# Change: DSF扫描网关与任务反馈修复

## Why

普通DSF系统注册时已保存QA Facade网关前缀，但后台扫描没有把该前缀传给scriptgen，导致所有Facade工具因无法构造`default_url`而标记为`invalid`，扫描Manifest无法发布。前端又把失败终态当作可继续流程，随后读取不存在的Manifest，并错误显示保存和扫描成功。

## What Changes

- 所有DSF系统扫描在调用scriptgen前动态读取当前系统本地QA网关前缀；显式扫描参数优先。
- Booking.Core继续基于同一前缀派生QA Job规则，不读取或传播Labrador Token。
- 缺少网关前缀时在启动scriptgen前返回稳定、可操作的领域错误。
- 前端扫描任务失败时立即中止后续Manifest读取，不再展示成功提示。
- 扫描目录加载失败会阻止保存/重扫成功Toast，避免成功与失败同时出现。

## Scope

只修复源码扫描参数传递和控制台任务反馈。保留已注册系统、本地Token和历史失败诊断产物；修复后用户可直接重新扫描。

## Non-Goals

- 不自动发送生成的Curl或访问QA。
- 不执行DSF工具、数据库、Redis或MQ校验。
- 不把本地Token写入扫描请求、任务、日志、Manifest或Snapshot。
- 不改变`dsf-execution-and-oracles`的`WAITING_QA_INPUT`状态。
