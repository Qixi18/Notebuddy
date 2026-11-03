# 当前架构说明

本页描述 `feat/overall-inspection` 当前实现；跨协作者共同入口是根目录 [AGENTS.md](../AGENTS.md)，详细契约见 [backend-data-contract.md](backend-data-contract.md)。历史设计只作为历史证据，不可覆盖当前代码事实。Notebook 路由文件拆分已完成，但后端 handler/service/事务边界仍在 Proposed 整改范围内。

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

`apps/backend/app/api/v1/routes.py` 注册 config、courses、materials、jobs、knowledge、notebook、generation、assistant、conversations、agent、feedback、backup、terms、forest、forest_imports、quiz 路由。Notebook 正文保存/恢复、图片所有权、章节重排和阅读位置分别由 `app/services/notebook_document.py`、`app/services/notebook_order.py`、`app/services/notebook_reading_position.py` 编排；生命周期的移动、绑定、恢复、删除、创建和重命名由 `app/services/notebook_lifecycle.py` 编排，建议审核由 `app/services/notebook_suggestions.py` 编排，附件/封面变更与资源缺失状态更新由 `app/services/notebook_resources.py` 编排。这些渐进用例服务仍直接使用 SQLAlchemy Session 和 HTTPException，尚未形成独立 repository/domain 层；资源读取与 HTTP FileResponse 仍保留在资源 Route。正文修改仍必须通过 `notes/store.py` 的唯一写入机制。持久任务由 `apps/backend/app/workers/runner.py` 运行。缺少 Worker 时，异步解析/生成可滞留队列。

Notebook 上传登记 Asset/资源归属和持久任务；批次完成后由后台协调解析与生成输入。解析结果通过 Asset 关联当前/历史 ParseRun。生成 Worker 对解析结果执行质量检查与来源校验，使用任务基准 revision 与当前正文合并；revision 冲突应保留用户修改。上传后初始/增量生成允许在门禁后写正文；Agent 对已有正文的主动改动通过 `NotebookEditSuggestion` 或受控操作，并核对基准 revision。

课程资料接口接收 PDF、PPTX、DOCX；Notebook 图片资源使用独立上传接口接收 PNG、JPEG、WebP、GIF。PPTX/DOCX 当前通过受限兼容适配器生成 DocumentIR，不提供与 PDF/图片相同的完整结构质量保证；下游生成仍按 DocumentIR 质量报告门禁。

## Web 与知识森林

前端页面路由在 `apps/web/src/App.tsx` 声明为 `appRoutes` 嵌套路由对象，由 `apps/web/src/main.tsx` 直接创建 `createBrowserRouter`。`AppRoot` 提供 Workspace 状态，`AppLayout` 负责组合页面 shell，`AppSidebar` 承担侧栏界面，`NotebookNavigationGuard` 处理脏正文离开拦截，`useAssistantDockController` 管理助手坞状态。页面路由和旧路径重定向位于 shell 子路由；全局、Notebook、森林及答疑路由有 `errorElement`。当前未使用 loader/action。Notebook、助手坞和森林页面按需加载。资料页中的旧路径有 `LegacyMaterialsRedirect`，旧 `MaterialsPage.tsx` 仍在仓库，不能仅据文件存在推断它是当前主路由。知识森林从课程、Notebook/Section 和关系数据构建展示及定位，不复制正文。Agent 通过服务端工具读取 Notebook 与证据，并按课程/Notebook 范围校验。

具体请求、兼容接口和验证级别见 [API 契约](api.md)；DocumentIR 版本关系见 [解析说明](parsing.md)。

## 本地数据与运行

默认数据根目录是仓库 `data/`，可由 `NOTEBOOK_DATA_DIR` 覆盖；数据库和上传原件不进入 Git。启动入口、迁移副作用、端口和测试隔离以 [README](../README.md)、[operations](operations.md) 和脚本源码为准。`dev.ps1` 启动前会执行数据库迁移，因此只允许在用户已选择的本地开发数据目录使用；本轮不操作真实库。

## 架构决策

当前基线记录在 [ADR-0001](architecture-decisions/ADR-0001-notebook-document-source-of-truth.md)，状态 Proposed，未获审核。未来全局变化需先记录提案、同步 README 公告、数据契约、API、测试及 Agent 影响；不得把历史计划当作实施依据。
