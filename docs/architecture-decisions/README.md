# 架构决策记录

本目录记录跨模块架构决定。只有经协作者明确审查的条目才可标为 `Accepted`；`Proposed` 是讨论中的基线，不是已批准的新计划。全局变化同步更新 README 架构公告、数据/API 契约、受影响测试和 PR 中的“全局架构变更（需跨 Agent 同步）”说明。

以下实施和自动验证文字按各 ADR 标注的历史提交、日期理解；代码可能已落地，但技术审查与真实材料、模型、浏览器验收仍是不同事项。当前提交的验证状态见 [验收记录](../acceptance.md)。ADR-0001 至 ADR-0004 均未在本次文档治理中改变决策状态，也没有仅因后续实现而标为 Superseded。

## 当前记录

- [ADR-0001：Notebook 正文权威源与资料处理边界](ADR-0001-notebook-document-source-of-truth.md) — Proposed，尚未审核。
- [ADR-0002：Notebook 核心架构整改路线](ADR-0002-verified-notebook-assistant-and-file-budget.md) — Proposed，A1/A2、B1/B2、C1/C2、S1–S8 有实现记录；自动回归已完成，真实材料/模型/浏览器及迁移恢复验收仍未完成。协作者审核前不能视为 Accepted。
- [ADR-0003：后端路由业务职责下沉](ADR-0003-service-layer-final-extraction.md) — Proposed，Notebook/Material 等 Service 下沉与对应自动验证已完成，等待技术把关者审查。
- [ADR-0004：剩余复杂路由用例的应用服务边界](ADR-0004-remaining-business-use-cases.md) — Proposed，`f52ced9` 基线上的会话/森林/知识/课程用例分层与自动验收已完成；真实资料、模型及浏览器人工验收仍有明确缺口，等待技术审查。
- [ADR-0005：恢复答疑过程可见性与 Notebook 编辑建议工具](ADR-0005-restore-agent-streaming-and-notebook-edit-suggestions.md) — Proposed，修订 ADR-0002 S2（P0-QA-02）"过程不可见"部分并保留其核验留档契约；等待技术把关者与原作者复核。

## 状态含义

- **Proposed**：记录现状或待审核决策，不代表批准实施。
- **Accepted**：由审查者明确接受并记录日期。
- **Superseded**：被后续 ADR 取代，保留历史上下文。
