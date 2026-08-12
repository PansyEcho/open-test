# ADR-0001：同仓库旁路构建V2

## 状态

已接受。

## 决策

在当前仓库新增 `opentest` V2包，legacy `ai_test_platform` 保持可运行但停止扩展。V2能力完成纵向闭环后，前端和API逐步切换，legacy删除另立变更。

## 原因

- 现有scriptgen扫描、执行断言和测试资产值得复用。
- 现有 `Platform` 大类和每项目JSON存储不适合新的知识模型。
- 新开仓库会复制基础设施并失去现有回归保障。

## 结果

- 迁移期会并存两套应用入口。
- V2必须通过明确适配器复用legacy逻辑，禁止直接依赖legacy `Platform`。
