# NoteBuddy 文档导航

## 当前入口

- [项目运行、环境准备与启动](../README.md)
- [代码架构](architecture.md)
- [接口](api.md)、[解析](parsing.md)、[知识整合](knowledge-integration.md)
- [后端调用与业务数据存储契约](backend-data-contract.md)：并行开发共用的调用链、数据归属与本地存储路径
- [数据迁移](migrations.md)、[运维](operations.md)、[安全](security.md)
- [验收矩阵](acceptance.md)、[证据约束](evidence.md)、[RAG 评估](rag-evaluation.md)

## 历史设计与实施记录

- `superpowers/specs/`：各专项设计和未来部署方案；设计不代表已验收。
- `superpowers/plans/`：实施计划。
- `handoffs/`：各阶段交接与验证记录。
- `design-references/` 和根目录 SVG：视觉参考或提案。

查代码时从 `apps/web/src/pages/` 的路由入口或 `apps/backend/app/api/v1/` 的接口入口进入；树绘制在 `apps/web/src/features/tree/`，笔记编辑与阅读在 `apps/web/src/features/notebook-editor/`，森林关系仍在 `apps/web/src/features/forest/`。
