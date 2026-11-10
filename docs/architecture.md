# 当前架构说明

本页描述当前仓库源码中的实现；分支职责见 [协作指南](../CONTRIBUTING.md)，Agent 简明规则见根目录 [AGENTS.md](../AGENTS.md)，模块职责见 [module-map.md](module-map.md)，详细数据契约见 [backend-data-contract.md](backend-data-contract.md)。历史设计只作为历史证据，不可覆盖当前代码事实。Notebook 与 Material 的复杂读取和写入、会话持久化与答疑编排、Forest 导入/读取、Knowledge 投影/审核、复杂课程聚合与生命周期均由应用服务承接；课程等简单列表允许路由直接查询。Service 使用 SQLAlchemy Session，不引入 Repository。Notebook/Material 的初始分层记录在 [ADR-0003](architecture-decisions/ADR-0003-service-layer-final-extraction.md)，其余复杂用例及验收范围记录在 [ADR-0004](architecture-decisions/ADR-0004-remaining-business-use-cases.md)；两份 ADR 仍为 Proposed，等待技术审查。

## 正文与来源

```text
Notebook / Asset
  → 持久上传与处理任务
  → Document Processing / DocumentParseRun / DocumentIR
  → 生成快照与质量门禁
  → Notebook.document_json（唯一正式正文，document_revision）
  → 编辑器、章节投影、检索派生索引、森林导航、范围化 Agent 读取
```

Notebook 正文由 `apps/backend/app/notes/store.py` 的统一写入逻辑保存，并维护 revision、历史快照与章节索引。面向 API 的正文保存、历史恢复、图片资源归属检查和事务边界集中在 `apps/backend/app/services/notebook_document.py`；路由负责 Notebook 身份解析及响应适配，正文修改仍必须经 `write_document`。`apps/backend/app/notes/index.py` 中的 `NotebookSection` 是可重建目录/文本投影，不是第二正文源。`DocumentIR` 与 ParseRun 是源文件解析的版本化结构和质量信息；检索块、森林目录为派生数据。旧 `Note.content_markdown`、NoteRevision 与 `NotebookGenerationCandidate` 仍有迁移、兼容或历史含义，不应据此恢复旧正文链或删除历史资料。

## 请求与后台任务

2026-11-08：新 `llm` 上传通过 provider 快照的 `reading_mode=hybrid` 选择 `document_processing/hybrid.py`：本地按页提取，必要时用已锁定本地 MinerU，再对未解决疑点调用原视觉 reader。原始数学几何、向量、小图或缺布局证据时保守读取原页，防止另一解析器的纯文本结果覆盖风险。旧快照缺此字段继续旧全视觉 reader。新混合生成使用 `generation/draft.py` 的受类型校验教学草稿、本地编译到 Tiptap；两条生成路线复用 `generation/resume.py`，已通过结构/公式/来源校验才缓存。每次 DeepSeek 非流式请求通过 `ai/request_control.py` 的任务检查，包括内部重试，正式正文仍原子调用 `write_document`。详见 ADR-0006（Proposed）；数据表/API 路线枚举不变。

```text
React 页面 / Feature → Web API Client → FastAPI Router
                                      → Application Services → Domain Modules
                                                             → Infrastructure（数据库、文件存储、模型客户端）
持久任务 → Worker → Application Services / Domain Modules → 同一基础设施与正文写入路径
```

这是当前代码的逻辑依赖方向，不要求每个 Router 一对一建立 Service，也不暗示存在独立 BFF。数据库保存 Notebook 正文与 revision、Asset/ParseRun/任务状态和关联关系；文件存储保存上传原件及可重建的派生文件。AI 答疑由会话/答疑应用服务协调范围化证据、Notebook 专属核验、模型调用和响应；Document Processing 从 Asset 原件生成带位置与质量状态的 DocumentIR，生成任务再从有效来源构造正文候选。

`apps/backend/app/api/v1/routes.py` 注册 config、courses、materials、jobs、knowledge、notebook、generation、assistant、conversations、agent、feedback、backup、terms、forest、forest_imports、quiz 路由。Notebook 正文/历史、生命周期、阅读位置、资源、关系和建议用例位于相应 `app/services/notebook_*.py`；正文写入继续经 `notes/store.py`。Materials 子路由保留既有 HTTP 兼容入口，兼容文件聚合位于 `app/services/material_reads.py`，DocumentIR 查询、兼容页面/证据投影、页面渲染与图片路径解析位于 `app/services/document_reads.py`。上传批次查询由 `app/services/notebook_generation_inputs.py` 提供；解析重试、重解析、OCR、图片重试、任务/预算读取、路线切换和取消由 `app/services/asset_processing.py` 与 `app/services/processing_budget.py` 提供。会话查询、CRUD、幂等消息保存和失败记录位于 `app/services/conversations.py`，答疑用例编排位于 `app/services/assistant_execution.py`；Forest 的复杂读取及导入任务分别位于 `app/services/forest_reads.py`、`app/services/forest_imports.py`；Knowledge 图/结构/提案查询与审核位于 `app/services/knowledge_reads.py`；课程概览及创建、改名、访问、删除/恢复事务位于 `app/services/course_management.py`。课程简单列表读取仍允许路由直接查询。共享数据范围检查位于 `app/services/resource_scopes.py`。预期业务错误使用框架无关的 `ApplicationError`（Forest 领域层使用框架无关领域错误），由应用边界映射 HTTP 响应；路由保留 HTTP 参数校验、文件传输适配和响应模型。底层仍直接使用 SQLAlchemy Session，未引入 Repository。持久任务由 `apps/backend/app/workers/runner.py` 运行。缺少 Worker 时，异步解析/生成可滞留队列。

Notebook 上传登记 Asset/资源归属和持久任务；批次完成后由后台协调解析与生成输入。解析结果通过 Asset 关联当前/历史 ParseRun。生成 Worker 对解析结果执行质量检查与来源校验，使用任务基准 revision 与当前正文合并；revision 冲突应保留用户修改。上传后初始/增量生成允许在门禁后写正文；Agent 对已有正文的主动改动通过 `NotebookEditSuggestion` 或受控操作，并核对基准 revision。

课程资料接口接收 PDF、PPTX、DOCX；Notebook 图片资源使用独立上传接口接收 PNG、JPEG、WebP、GIF。PPTX/DOCX 当前通过受限兼容适配器生成 DocumentIR，不提供与 PDF/图片相同的完整结构质量保证；下游生成仍按 DocumentIR 质量报告门禁。

## Web 与知识森林

前端页面路由在 `apps/web/src/App.tsx` 声明为 `appRoutes` 嵌套路由对象，由 `apps/web/src/main.tsx` 直接创建 `createBrowserRouter`。`AppRoot` 提供 Workspace 状态，`AppLayout` 负责组合页面 shell，`AppSidebar` 承担侧栏界面，`NotebookNavigationGuard` 处理脏正文离开拦截，`useAssistantDockController` 管理助手坞状态。页面路由和旧路径重定向位于 shell 子路由；全局、Notebook、森林及答疑路由有 `errorElement`。当前未使用 loader/action。Notebook、助手坞和森林页面按需加载。资料页中的旧路径有 `LegacyMaterialsRedirect`，旧 `MaterialsPage.tsx` 仍在仓库，不能仅据文件存在推断它是当前主路由。知识森林从课程、Notebook/Section 和关系数据构建展示及定位，不复制正文。Agent 通过服务端工具读取 Notebook 与证据，并按课程/Notebook 范围校验。

具体请求、兼容接口和验证级别见 [API 契约](api.md)；DocumentIR 版本关系见 [解析说明](parsing.md)。

## 本地数据与运行

默认数据根目录是仓库 `data/`，可由 `NOTEBOOK_DATA_DIR` 覆盖；数据库和上传原件不进入 Git。启动入口、迁移副作用、端口和测试隔离以 [README](../README.md)、[operations](operations.md) 和脚本源码为准。`dev.ps1` 启动前会执行数据库迁移，因此只允许在用户已选择的本地开发数据目录使用；本轮不操作真实库。

## 架构决策

当前正文边界记录在 [ADR-0001](architecture-decisions/ADR-0001-notebook-document-source-of-truth.md)，状态 Proposed，未获审核。后端路由分层进度记录在 [ADR-0003](architecture-decisions/ADR-0003-service-layer-final-extraction.md) 和 [ADR-0004](architecture-decisions/ADR-0004-remaining-business-use-cases.md)，两者仍待技术审查。未来全局变化需先记录提案、同步 README 公告、数据契约、API、测试及 Agent 影响；不得把历史计划当作实施依据。
