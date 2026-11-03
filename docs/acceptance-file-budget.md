# 单文件 10 元预算验收记录

> 对应路线图：批次 S4（P1-BUD-01…05）
> 状态：**Fake Provider / 隔离 SQLite 自动验证已完成；真实供应商账单核对未执行**
> 基线：`feat/overall-inspection`，本地工作树（未提交）

## 1. 口径（必须原样使用）

> 在**配置的价格、图片 Token 上界、汇率快照与供应商 usage 假设下**，本实现能拦截
> 超过 10.00 CNY 的**新增**模型请求。

**不能**表述为"实际费用绝对不可能超过 10 元"：真实账单还受供应商隐藏费用、
计价口径变化、汇率波动、图片计量方式影响。账本会对超出预估的调用记 `overrun`。

## 2. 收费链路与账本

| 阶段 | 入口 | 账本 |
|---|---|---|
| 视觉读页 | `document_processing/llm_reader.py` | 同 Asset 账本 |
| 规划 | `generation/llm_planner.py` | 同上 |
| 正文生成 | `generation/composer.py` | 同上 |
| 格式修复 / 重试 | `generation/*`、Worker | 同上 |
| 自动关系生成 | 暂停（预算安全取舍） | — |

- 账本主键 `AssetProcessingBudget.asset_id`，上限 `BUDGET_LIMIT_FEN=1000`。
- 共享调用对每个参与 Asset **重复计整笔**（保守，不做分摊）。
- `usage` 缺失 → `uncertain`，额度保留；超预估 → `overrun`；两者都封锁后续付费。

## 3. 自动测试证据

| 用例 | 文件 | 结论 |
|---|---|---|
| 四个阶段共享一本账且不越上限 | `tests/test_file_budget_end_to_end.py` | ✅ |
| 余额不足时**不发起**网络请求 | 同上 | ✅ |
| 同阶段重试不清零账本 | 同上 | ✅ |
| 进程/会话重建后账本延续 | 同上 | ✅ |
| usage 缺失后所有后续阶段被拦 | 同上 | ✅ |
| 共享 Asset 各自记整笔 | 同上 | ✅ |
| 账单低于预留 → 只按实际 usage 扣费 | `tests/test_budget_invoice_reconciliation.py` | ✅ |
| 账单高于预留 → `overrun` 且永久封锁 | 同上 | ✅ |
| usage 缺失 → `uncertain` + 保留额度 | 同上 | ✅ |
| 汇率过期 / 价格版本缺失 → fail closed | 同上 | ✅ |

## 4. 尚未验证

1. 真实供应商账单（需用户单独批准一次小额真实调用）。
2. 图片 Token 上界 `NOTEBOOK_VISION_MAX_IMAGE_TOKENS` 的真实计量校准。
3. 汇率快照来源的长期可维护性（当前是维护者手工录入）。
4. 前端"预算耗尽/费用待核"提示在真实错误码下的表现（只有 Fake Provider 覆盖）。
