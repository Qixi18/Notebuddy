# ADR-0004：剩余复杂路由用例的应用服务边界

- **状态：Proposed**（实现和自动验证已完成，待技术把关者审查）
- **日期：**2026-11-03
- **代码基线：**`feat/overall-inspection`，`f52ced9`
- **前置状态：**ADR-0003 的会话/Notebook/Material 分层改动保留在未提交工作区；本 ADR 扩展收尾范围，不改变 ADR-0003 的已述数据约束。
- **范围：**会话答疑编排、Forest 导入和任务用例、知识结构查询/提案审核、复杂课程聚合及生命周期操作、有效架构边界测试、旧兼容路径盘点和验收记录。

## 背景与证据

在 `f52ced9` 的干净基线中，`conversations.py` 混合会话 ORM、幂等事务和 AI 答疑流水线；`forest_imports.py` 负责查询/投影、导入确认/撤销和任务事务；`knowledge.py` 直接查询并组装 NotebookSection 投影且在路由中应用 KnowledgeProposal；`courses.py` 在路由组装多来源课程概览并处理若干课程事务。`curriculum_confirmation.py` 与 `curriculum_revert.py` 直接依赖 FastAPI 异常，使应用服务无法独立处理这些领域失败。

干净基线验收（`pwsh -NoProfile -File .\scripts\test.ps1`，日志 `.runtime/logs/test-20261103-201721-18504.log`）：Ruff 通过；后端 573 passed、4 skipped；Web 导航 52/52；Vitest 404 passed、22 failed，失败集中于 5 个 UI 测试文件。基线 Web 构建和 Desktop 构建另行通过。该结果是 `f52ced9` 证据，不代表本 ADR 改动回归。

## 决策

1. 只为多步骤业务编排、数据聚合、确认/撤销及事务建立清晰应用服务入口；简单 CRUD 列表不以消除每条 SQL 为目标。
2. 会话 Router 调用会话/消息 Service 和 `assistant_execution` 用例；AI 专业能力仍由现有 `app.ai` 模块实现。幂等、来源持久化和失败记录语义保持原样。
3. Forest Router 通过应用服务组织现有 `forest/` 能力，不复制解析、确认、撤销或任务实现；上传文件仍由 HTTP 层接入，再以二进制流交给用例。
4. Knowledge 图和结构是 Notebook 派生只读投影；提案审核继续使用 `app.knowledge.proposals`，由应用服务管理归属检查和事务。
5. Courses 的复杂概览、创建/改名/访问/删除/恢复事务使用应用服务；简单列表读取可继续由 Router 直连 SQLAlchemy。
6. 应用服务与领域能力不导入 FastAPI/HTTPException；业务失败使用框架无关异常，由服务或全局 HTTP 适配器映射。不得让失败映射改变现有接口状态码/详情。
7. 强化架构测试以检查具体复杂用例边界、AI 编排位置、服务和领域依赖方向，而不是禁止全部 Router SQL。
8. 审计旧 Note/API/解析路径时以运行时引用、调用方及历史数据职责为证据；未证明可安全移除的兼容代码与迁移保留并标注状态。

## 兼容性、数据与回滚

- 保持当前 OpenAPI 路径、方法、请求/响应字段和成功/失败状态码；回归使用 OpenAPI 与现有接口契约测试。
- 不改变 `Notebook.document_json`、revision/CAS、DocumentIR、知识森林派生数据或迁移；所有正文写入继续经过 `notes/store.py`。
- 不删除 Note/Material 历史表、迁移或兼容 API；不读取/修改用户真实数据库，不调用外部模型。
- 可按模块回退 Service/Router 委托改动；异常类型变化仅在应用边界内转换，无数据回滚步骤。

## 验证计划

- 扩展后端架构边界测试，覆盖会话、Forest 导入、Knowledge、Courses 的复杂边界，并保留简单读取例外。
- 运行 Ruff、全量后端 pytest、OpenAPI/兼容契约测试、Web 测试/构建和 Desktop 构建；逐项列明基线已失败的 Web 测试。
- 审查正式正文写入点、DocumentIR 读取入口、前端仍调用的旧 API 和解析模块引用；不把静态搜索当作真实资料/浏览器验收。
- 真实文件、浏览器人工流程、真实模型/质量和隔离旧库迁移/恢复仍单独标为未验收。

## 实施与验证结果（2026-11-03）

- 会话的 ORM 读写、幂等事务和失败状态持久化位于 `services/conversations.py`；答疑编排位于 `services/assistant_execution.py`。
- Forest 导入、重试/确认/撤销和任务查询位于 `services/forest_imports.py`；森林读取/搜索/关系投影位于 `services/forest_reads.py`。Forest 领域失败不再依赖 FastAPI 异常。
- Knowledge 图/结构/提案查询与审核位于 `services/knowledge_reads.py`；复杂课程概览及访问、创建、改名、删除/恢复事务位于 `services/course_management.py`。简单课程列表查询保留在 Router。
- `test_backend_architecture_boundaries.py` 检查上述复杂边界、服务依赖方向和简单列表例外；相关 Forest、Knowledge、课程、会话契约测试通过。最终完整执行证据列于 `docs/acceptance.md`。
- 仓库静态引用核查确认旧 Note API 客户端与 `useNoteEditor` 没有运行时导入方；旧迁移、模型和历史资料保留。旧前端 URL 是 `/courses` 重定向，不是有效后端 Note API。
- 不修改 OpenAPI 路径/schema、数据库 schema、正式正文写入路径或迁移；不读取真实用户库，也未调用外部模型。
- 真实 PDF/图片质量、模型请求、真实浏览器用户流程、旧库迁移和备份恢复仍未人工验收；自动化结果不能替代这些验收。

## 影响与审查

这是跨 API、Services、Forest/Knowledge 领域、测试和架构文档的 L3 调整。技术把关者审查之前保持 Proposed；本 ADR 及实现不代表架构已 Accepted，也未授权提交、推送或合并。
