# NoteBuddy 核心架构整改实施盘点

盘点日期：2026-11-01（Asia/Shanghai）

规划依据：`Notebuddy开发与ChatGPT的交流信息/2026-11-01-Notebuddy-Codex-核心架构整改开发规划.md`

盘点基线：`origin/feat/overall-inspection`，执行时 `git fetch origin` 后 HEAD=`67677dd8771f2fe756d2f29a986102a64655a730`

本盘点所在工作区：`feat/overall-inspection`，HEAD 与上述远端基线相同。
状态定义：**确认存在**=在该基线源码中定位到；**已消失**=在约定搜索范围中核实不存在；**未确认**=仅凭静态源码不能确定，需运行态或更深入验证。

> 第 1–9 节为初始静态调查快照，不代表规划功能已经实现或验收。调查未读取本地 `.env`、用户真实数据库或上传材料；后续批次状态见第 10 节。

## 1. 基线与工作区

- **确认存在**：基线远端分支 `origin/feat/overall-inspection`，HEAD `67677dd`（提交说明：`fix: polish knowledge garden and assistant messaging`）。
- **确认存在**：当前主工作区 `D:\工作台\Notebuddy软件开发\Notebuddy` 留在 `feat/debug-integration`，HEAD `e8e325a`，与 `origin/feat/debug-integration` 对齐；其中有被 Git 忽略的 `.env`、`data/`、运行环境和缓存。
- **确认存在**：本盘点在独立 worktree `D:\工作台\Notebuddy软件开发\Notebuddy-overall-inspection`，未切换或改写主工作区。
- **未确认**：本基线的运行配置、实际模型与供应商价格、真实材料解析质量和浏览器行为；需在后续隔离测试/人工验收中核实。

## 2. A 包：答疑、Notebook、DocumentIR、Web 与 SSE

| 规划调查项 | 状态 | 源码现状及接口 | 相关测试 / 模型 / 迁移 |
|---|---|---|---|
| 独立答疑页旧 Note 语义及建议 UI | **确认存在** | `apps/web/src/pages/AssistantPage.tsx` 导入 `useNoteSuggestions`、渲染 `NoteSuggestionCards`；调用配置 WebSearch 状态及 Agent/会话 API。 | 前端 `assistant-notebook-scope.test.tsx`、`use-conversation.test.tsx`、助手 UI 测试。 |
| AI Dock 上下文/旧写回并存风险 | **确认存在** | `apps/web/src/features/assistant/AssistantDock.tsx` 导入 `useNoteSuggestions`、渲染 `NoteSuggestionCards`，提供 review/undo；它也使用 Agent SSE。 | 前端 `agent-dock.test.tsx`、`agent-conversation-scope.test.tsx`、`agent-sse.test.ts`。 |
| Agent SSE 在最终核验前转发正文 | **确认存在** | `apps/backend/app/api/v1/agent.py`：`POST /conversations/{conversation_id}/agent-messages`；流式事件按 Agent 循环事件转发，存在 `delta` 路径。 | 后端 `test_agent_reasoning_visibility.py`、`test_agent_notebook.py`；前端 `agent-sse.test.ts`。需新增“核验前零 delta”验证。 |
| Agent 自由工具循环和编辑建议工具 | **确认存在** | `apps/backend/app/ai/agent_loop.py`、`agent_tools.py`；工具集合包含 `read_notebook`、课程检索、Web 搜索和 `propose_notebook_edits`。`apps/backend/app/ai/prompts.py` 仍指示可提交建议。 | 后端 `test_agent_tool_scope_gates.py`、`test_notebook_edit_suggestion_review.py`、`test_agent_notebook.py`。建议接口与数据模型须停用入口但保留兼容。 |
| Notebook 定向 DocumentIR 检索 | **确认存在但能力未满足规划** | `apps/backend/app/retrieval/service.py::retrieve` 分为文档与 Notebook 检索；当前接口尚不能直接证明“仅检索所选 Notebook 当前有效 ParseRun”，需逐段核查过滤条件和资产关联。 | `test_document_retrieval_embeddings.py`、`test_evidence_notebook.py`、`test_document_service.py`。模型含 `NotebookAsset`、`DocumentParseRun`、`DocumentBlock`、`DocumentChunk`、来源映射等。 |
| WebSearch 与来源记录 | **确认存在** | `apps/backend/app/web_search/service.py`、`tavily.py`、`source_review.py`、`policy.py`；存在搜索策略、可用性、来源审议及日限额记录函数。 | 后端 `test_web_search_service.py`、`test_assistant_evidence.py`；普通问答外部搜索需与文件预算区分。 |
| 会话 `scope='note'` / `note_id` 兼容字段 | **确认存在** | `apps/backend/app/schemas/conversations.py` 中会话和消息协议仍允许 `note` / `note_id`；`NotebookDocumentContext.course_id` 仍为必填。Agent API 将读取上下文里的 note 标识映射到 Notebook，并校验归属。 | `Conversation`、消息/证据模型在 `apps/backend/app/db/models.py`；迁移 `c5a7b2e91f34_conversation_scope.py`、`a41d9c7e2b60_message_evidence_source_snapshot.py` 等。需要设计 `notebook_id` 与可空课程 ID 的兼容迁移。 |
| 未分类 Notebook 的答疑会话 | **确认存在但契约受阻** | 有 `/notebooks/unbound` 相关 Notebook API；Agent/检索上下文仍有课程归属校验，未分类 Notebook 不能用可靠的独立会话协议直接满足规划。 | `test_notebook_workspace.py`、`test_conversation_scope.py`、`test_agent_notebook.py`。迁移见 `b7e4c2a19f63_unbound_notebooks.py`、`e4c73a10d2f5_unbound_notebook_documents.py`、`f7a5c2d901be_unify_unbound_notebooks.py`。 |
| 前端答疑当前 API 契约 | **确认存在** | `apps/web/src/api/conversations.ts`：课程路径创建/列出会话、`/conversations/{id}/messages` 普通消息、会话维护；创建/发送仍用 `scope='note'` 与 `note_id`。`apps/web/src/api/agent.ts`：`POST /api/v1/conversations/{id}/agent-messages`（SSE）。`apps/web/src/api/notes.ts`：前端仍调用 `/api/v1/notes/{id}/suggestions`、`/api/v1/courses/{id}/note-suggestions` 与 review 路由。 | 后端 `api/v1/conversations.py`、`api/v1/agent.py`；须检查 `routes.py` 注册。现有数据契约指出旧 NoteSuggestion API 路由可能未注册，故“前端调用代码存在”已确认，“端点当前可用”未确认，必须在 A1 实测注册与行为。 |
| 前端 Notebook 页面当前 API 契约 | **确认存在** | `apps/web/src/api/notebook.ts`、`materials.ts`：课程文档走 `/courses/{courseId}/notebooks/{notebookId}/document`，未分类走 `/notebooks/unbound/{notebookId}/document`；共享 `/notebooks/{id}/generation-jobs`、`upload-batches`；资源使用 `/notebooks/{id}/assets`、`/assets/{assetId}/parse-runs?notebook_id=...`。 | 后端注册集中在 `api/v1/notebook.py`、`materials.py`、`generation.py`；编辑保存共享能力但路由仍分叉。 |
| Notebook 正文、revision/CAS、历史 | **确认存在** | `apps/backend/app/notes/store.py::write_document`；前端 `NotebookEditor.tsx`、`useNotebookSave.ts`。规划要求保留 `Notebook.document_json` 唯一可写正文源及 revision CAS。 | `Notebook`、`NotebookDocumentRevision`、`NotebookBlockSource`、`NotebookSection`；迁移 `a93f1c7d6e42_notebook_document.py`、`b93a1c7e5d20_notebook_history_attachments.py`、`d9e4a7b21c60_document_ir_persistence_contract.py` 等。 |

### A1 需要补齐的契约问题

1. 明确前端答疑页与 Dock 的实际端点、payload 字段和所有 NoteSuggestion 展示/写回入口；不得只删除组件调用而遗漏其他入口。
2. 定义旧 `scope='note'` 历史会话如何按 Notebook ID 读取，避免把退役 Note ID 当成 Notebook ID；映射必须验证真实关系。
3. 为 `course_id` 可空、以 `notebook_id` 为会话目标的未分类 Notebook 方案提交迁移设计，再进入数据库变更。
4. 禁止 Agent 的正文编辑建议新建路径，但保留已发布表、迁移、历史读取兼容。

## 3. B 包：文档处理、视觉模型与成本预算

| 规划调查项 | 状态 | 源码现状及接口 | 相关测试 / 模型 / 迁移 |
|---|---|---|---|
| 当前上传/解析/生成端点 | **确认存在** | `api/v1/materials.py`：`GET/POST /notebooks/{notebook_id}/assets`、资产 restore/inline/delete、upload-batches 查询/complete、`GET /assets/{asset_id}/parse-runs`、document/run/page evidence/render/figure/coverage、资产 processing-jobs、parse-retries、processing-route、cancel-processing；旧 materials 路径另有 upload/retry/reparse/ocr。`api/v1/generation.py`：`POST/GET /notebooks/{notebook_id}/generation-jobs`、`GET /.../{job_id}`、retry、cancel。Notebook 正文和附件端点在 `api/v1/notebook.py`，见 C 包。 | 前端主要调用 `apps/web/src/api/materials.ts`、`notebook.ts`；逐项 UI 使用情况需实现时追踪。后端测试 `test_processing_routes.py`、`test_document_service.py`、`test_llm_document_processing.py`、`test_processing_review_regressions.py`、`test_generation_pipeline.py`。 |
| `standard` / `llm` 处理路由 | **确认存在** | `apps/backend/app/document_processing/routes.py` 有路由解析、限制、`provider_snapshot()`、配置和客户端创建；解析服务在 `document_processing/service.py`。全程 AI 读页见 `llm_reader.py`、`rendering.py`、`checkpoints.py`。 | 迁移 `a5e3c8d1f209_dual_processing_routes.py`、`b3f1c7d92a10_document_processing.py`、`b7c2e1f5a901_phase_two_parse_evidence.py`。 |
| 视觉读页与检查点 | **确认存在** | `document_processing/llm_reader.py`、`rendering.py`、`checkpoints.py`；检查点使用 `ProcessingStep` 保存阶段数据。具体模型能力预检与图片输入兼容性**未确认**，需沿 provider client 和配置调用链验证。 | `ProcessingStep`、`DocumentParseRun`、`DocumentPage` 等模型；测试 `test_llm_document_processing.py`、`test_processing_routes.py`。 |
| 规划、正文生成及自动修复 | **确认存在** | `generation/llm_planner.py`、`composer.py`、`workers/notebook_generation_worker.py`；存在多个阶段/检查点以及最终 Notebook 写入。单次生成 token 上限不等于跨阶段人民币预算。 | `test_llm_generation.py`、`test_generation_pipeline.py`、`test_generation_quality_gate.py`、`test_document_ir_generation_e2e.py`；`NotebookGenerationJob`、`NotebookGenerationInput`、`NotebookGenerationCandidate`、`NotebookAsset`。 |
| 现有成本审计 | **确认存在，但不是预留预算闸门** | `apps/backend/app/services/provider_audit.py` 有调用开始/结束和 token 费用估算；`ProviderCall` 记录调用审计。 | `ProviderCall` 与迁移 `f7b9c2d6e401_provider_call_audit.py`。尚未确认可按 Asset 原子预留、跨阶段合计、崩溃保留和并发 CAS。 |
| 现有 generation “budget” | **确认存在，但单位为 token** | `apps/backend/app/generation/budget.py` 按输出 token 估算/分批；不能代表 10 CNY 费用约束。 | `test_generation_limits.py`、`test_generation_limits_db.py`。 |
| 视觉模型独立配置和能力预检 | **未确认 / 静态检查显示尚无完整契约** | `core/config.py` 有文档路由、生成器、DeepSeek 价格字段；路线配置通过通用 `provider_snapshot()`。静态搜索未发现完整的按用途模型配置和可靠 `supports_image_input` 预检契约。 | `test_settings_security.py`、`test_processing_routes.py`；模型能力来源及价格元数据需进一步盘点供应商适配层。 |
| 单文件 10 元预算和预算耗尽状态 | **未确认 / 静态检查显示尚无完整实现** | 未定位到跨解析、规划、生成、修复调用的统一 CNY 原子预算预留器或 `budget_exhausted` 统一状态。需逐个核查关系任务、重试、多个 Asset 共用批次的费用归属。 | 现有 `ProcessingStep`、`ProviderCall`、ParseRun/Job/GenerationInput 可作为设计输入；暂不表示能满足原子账本要求。 |

### B1/B2 关键待验证项

- 所有模型调用点、provider 请求上限、输入/图片计价口径、模型/缓存价格版本以及失败时 usage 缺失的处理。
- Asset 与 ParseRun、NotebookGenerationInput、关系任务的关系键和自动重试行为；确认多文件任务的费用能否稳定归属。
- 供应商真实计价规则和 CNY 汇率快照来源。缺乏可验证费用上界时必须 fail closed。
- 预算状态如何写入 ParseRun/Job/API 并展示在前端；保持已保存结果和检查点。

## 4. C 包：课程 / 未分类 Notebook Workspace

| 规划调查项 | 状态 | 源码现状及接口 | 相关测试 / 模型 / 迁移 |
|---|---|---|---|
| 课程 Notebook 页面 | **确认存在** | `apps/web/src/pages/NotebookPage.tsx`。 | 前端 Notebook 测试：`notebook-document.test.tsx`、`notebook-save.test.tsx`、`notebook-history-dialog.test.tsx`、`notebook-async-boundaries.test.tsx`、`notebook-math.test.tsx`、导航/图片/关系测试等。 |
| 未分类 Notebook 页面 | **确认存在** | `apps/web/src/pages/UnboundNotebookPage.tsx`，为另一套页面编排。 | `test_notebook_workspace.py` 覆盖部分后端契约；前端需要建立针对未分类页的功能矩阵。 |
| 可复用的编辑和保存内核 | **确认存在** | `features/notebook-editor/NotebookEditor.tsx`、`useNotebookSave.ts`；均需保留。两页面共享程度、上传/生成/历史/Dock 的逐项差异尚需功能对照。 | Notebook 正文与历史模型如上；不得重做存储契约。 |
| 共享 Workspace | **已消失（在该基线下尚未统一）** | 对比两个页面文件，尚无一个两条路由共用的完整 Workspace 页面实现；页面功能差异需先核对，不能据此直接删除旧页面。 | 前端 `notebook-navigation.test.ts` 等；C1 先做能力矩阵，C2 再切路由。 |

路由实际注册位置需要 A/C 实施前重新定位并记录；兼容路由不得中断。绑定/解绑、课程导航、未分类上下文、历史恢复、草稿及后台追加都须进入 C1 对照矩阵。

## 5. D 包：模块化单体分层

| 规划调查项 | 状态 | 源码现状及接口 | 相关测试 / 模型 / 迁移 |
|---|---|---|---|
| Notebook 后端 API 聚合 | **确认存在** | `apps/backend/app/api/v1/notebook.py` 是大型聚合路由，当前包含 unbound/course notebook、正文、revision、附件、资源、关系、建议等多组端点。 | `test_notebook_api_v2.py`、`test_notebook_document_v2.py`、`test_notebook_workspace.py`、历史/来源/关系/附件测试。 |
| Store/CAS 与业务契约 | **确认存在** | `apps/backend/app/notes/store.py` 的 `write_document()`；将 API 编排拆出时需保持 CAS、revision、来源映射及附件归属行为。 | 正文/来源/历史模型和对应既有迁移。 |
| Worker 对 API 层反向依赖 | **未确认** | 规划点名 generation input 与 API 函数依赖；需以导入图和符号引用逐项确认，不据规划描述直接认定存在。 | `notebook_generation_worker.py`、generation API 等；D 阶段补依赖方向报告及等价测试。 |
| 前端重型页面/状态职责 | **确认存在** | 两个 Notebook 页面与 Assistant 页面承担较多编排；是否需要拆 Hook 要以 A/C 完成功能链稳定后做依赖审查。 | 不提前引入新全局状态源或重做视觉。 |

## 6. 数据模型与 Alembic 迁移基线

- **确认存在**：`apps/backend/app/db/models.py` 定义 `Notebook`、`NotebookDocumentRevision`、`NotebookAsset`、`DocumentParseRun`、`ProcessingStep`、`NotebookGenerationJob`、`NotebookGenerationInput`、`NotebookSection`、`NotebookBlockSource`、`NotebookEditSuggestion`、`Conversation`、`ConversationMessage`、`ProviderCall` 等模型。
- **确认存在**：正文、DocumentIR、来源、历史、任务、会话、供应商审计均已有多条迁移；迁移版本目录含 33 个版本文件。
- **确认存在**：基线 Alembic 当前报告唯一 head 为 `f1a7c9d3e620`。数据库未连接、未升级。
- **明确边界**：不得改写已发布迁移或对主工作区 `data/notebook.sqlite3` 试迁移。新迁移必须另建隔离数据库验证，并测试从当前已发布 head 升级。
- **待补证**：`Conversation.course_id` 的数据库 nullability、SQLite 外键/索引影响、旧 note 会话样本和迁移前后读取行为；调查未读取真实用户记录。

## 7. 测试现状与本阶段基线

- **确认存在**：基线目录有 69 个后端测试文件、90 个前端测试文件（文件数，不等于测试用例数）。其中有若干 `manual_*` 后端评估/烟测脚本，不能将脚本存在写成实际验收。
- **已确认相关测试**：
  - 后端：`test_agent_notebook.py`、`test_agent_reasoning_visibility.py`、`test_agent_tool_scope_gates.py`、`test_conversation_scope.py`、`test_evidence_notebook.py`、`test_web_search_service.py`、`test_processing_routes.py`、`test_llm_document_processing.py`、`test_generation_pipeline.py`、`test_generation_limits_db.py`、`test_notebook_workspace.py`、`test_notebook_api_v2.py`。
  - 前端：`assistant-notebook-scope.test.tsx`、`agent-sse.test.ts`、`agent-dock.test.tsx`、`use-conversation.test.tsx`、`notebook-save.test.tsx`、`notebook-async-boundaries.test.tsx`、`notebook-navigation.test.ts`。
- **已运行的只读基线**：在此隔离 worktree 的源码目录中，使用已有 `.venv-document` 执行 `python -m pytest tests/test_agent_notebook.py tests/test_agent_reasoning_visibility.py tests/test_web_search_service.py tests/test_processing_routes.py -q`；退出码 `0`，**25 passed, 2 warnings**（pytest 插件重写警告、Starlette/httpx 弃用提示），无失败/跳过。测试 `conftest.py` 在导入应用前将 `NOTEBOOK_DATA_DIR` 指向按进程创建的临时目录，并清空付费供应商密钥，未使用主项目 `data/notebook.sqlite3`。
- **本阶段未运行**：完整 Vitest/Pytest、前端构建、迁移升级、浏览器人工验收。新 worktree 没有自己的 `node_modules`；后续前端验证需在隔离 worktree 安装锁文件依赖，或采用经确认的隔离依赖路径。后端 25 项是选定范围基线，不是完整回归。
- **不得声称**：仅凭测试文件存在不能声称验收通过；未做真实材料、真实模型或浏览器验证。

## 8. 风险与执行顺序

1. `feat/overall-inspection` 是规划指定的审查基线；主工作区当前仍在 `feat/debug-integration`。所有后续编辑继续留在独立基线 worktree，除非另行完成分支整合方案。
2. 规划 A1/A2 同时影响旧会话兼容、课程隔离、未分类 Notebook 和流式消息持久化；先完成 A1 契约表/迁移设计，再实现 A2 服务端缓冲与证据门禁。
3. B 需要先盘点每个付费调用及可验证价格上界；不能把 `ProviderCall` 的 token 后计费估算称为预留闸门。
4. C 需要先按功能制作对照表，完成 AI Context 和预算状态后统一页面。
5. 项目 `AGENTS.md` 规定全局架构变更先提交 Proposed ADR、更新 README 顶部公告、同步相关契约和测试，并经协作者审核后才能标为 Accepted；A1/A2、B1/B2 开始前应按该流程建立并评审提案。
6. 推荐批次仍按规划顺序 A1 → A2 → B1 → B2 → C1 → C2 → D；每批分别记录 diff、真实验证范围、失败/跳过、兼容性及回滚方式。

## 9. 本阶段文件与核查记录

- 新增：`implementation-inventory.md`。
- 生产代码、数据库、迁移、配置和真实用户数据：未更改。
- 已执行：fetch `origin`、确认目标 HEAD、建立隔离 worktree、源码/测试/迁移静态盘点、读取 Alembic head metadata。
- 远端状态记录：盘点期间 `origin/feat/overall-inspection` 的已 fetch HEAD 为 `67677dd8771f2fe756d2f29a986102a64655a730`；进入每个代码批次前须重新 fetch 并再次审查同名分支。

## 10. 后续批次状态：A1（2026-11-01）

此状态更新于主工作树 `D:\工作台\Notebuddy软件开发\Notebuddy` 的 `feat/overall-inspection`；初始盘点从隔离 worktree 迁移到主工作树后继续开发。前文的分支/路径说明只描述当时状态。

- **已实现（待最终批次评审）**：新增 `f2b7d9a1406c`，将 Notebook 会话目标独立保存为 `notebook_id`，`course_id=NULL`，保留历史 Note 字段和数据；Notebook 删除设空目标但保留会话历史；降级前遇到 Notebook-scope 行会拒绝执行。
- **已实现**：Notebook 专属创建/列表 API；课程与全局会话接口保留；通用消息读取允许无课程的 Notebook 历史；普通消息和 Agent 请求在 A1 返回 409，等待 A2，不回退到课程或最近访问上下文。
- **已实现**：旧 `scope='note'` ID 映射只在 Notebook/Note 唯一、同课程、未删除时返回；冲突、跨课程或目标失效时不猜测。AssistantPage/Dock 移除旧 Note 选择与 `reading_context.note_id` 发送，Dock 移除回答写入/替换正文入口。
- **已实现**：Agent 工具集合隐藏 `propose_notebook_edits`，Notebook scope 工具规范只包含锁定 Notebook 读取；已保留既有建议表、审查 API 和已发布迁移。
- **已通过的相关检查**：后端测试子集 `test_agent_notebook.py test_conversation_scope.py test_notebook_conversation_migration.py test_alembic_migration_drill.py` 在增补新断言后为 `20 passed, 2 warnings`；前端 `assistant-layout.test.tsx agent-dock.test.tsx use-conversation.test.tsx agent-conversation-scope.test.tsx` 为 `48 passed`；TypeScript `tsc -b`、Ruff 相关文件检查和 Vite 生产构建通过。Vite 提示主 bundle 超 500KB；未进行浏览器人工验收。完整 `scripts/test.ps1` 与本轮实现的协作者审核仍待完成。
- **下一步**：完成 A1 全库回归及实现评审后，提交 A1；随后按规划实现 A2 核验后 SSE 和专属证据服务。B1/B2/C1/C2/D 仍未实施。

### A1 完成记录（2026-11-01）

- 独立协作者审查：未发现阻断问题；明确 A2 需移除 Agent 对课程 ID 的假设并将 `read_notebook` 限定为会话绑定 Notebook。
- 完整验证命令：`pwsh -NoProfile -File .\scripts\test.ps1`，退出码 0；后端 Ruff 通过，pytest 439 passed / 4 skipped（2 warnings）；Web navigation 52 tests passed；Vitest 80 files / 411 tests passed；TypeScript、Web production build、Desktop main-process build 通过。Vite 有主 bundle 超 500 KB 警告。
- 变更范围：Notebook 会话数据契约/迁移/API、旧 Note ID 安全映射与前端入口清理、Agent 旧写回工具关闭、对应测试及 ADR/契约/README 记录。
- 人工浏览器验收：未执行。A1 暂时返回 409 阻止 Notebook 问答；实际问答路径属于 A2。
- 未覆盖风险：A1 未启用 Notebook 专属答疑；全量自动测试不代表真实模型/材料验收。

## 11. A2 完成记录（2026-11-01，本地未提交）

- **当前状态**：A2 实现、测试、独立评审已完成；改动仅在 `D:\工作台\Notebuddy软件开发\Notebuddy` 的本地 `feat/overall-inspection` 工作树，尚未提交或推送。当前 HEAD `0b0c0334faade82c4acdc719e9c0f02976d7515d`；这是最后确认的本地提交，不代表此后远端状态。用户明确要求后续不提交、不推送。
- **新行为**：新增 `apps/backend/app/ai/notebook_qa.py`；普通 JSON 会话与 Agent SSE 均调用同一 Notebook-first 服务。会话绑定和当前 revision 必须匹配；正文从 `Notebook.document_json` 及其 block_id/revision 建立；DocumentIR 只从同 Notebook 当前 completed ParseRun 和仍有效的 owner `NotebookAsset(role=source_material)` 读取。未分类 Notebook 可以做限定到 Notebook 的 WebSource 持久化。
- **核验/发布门禁**：初稿不进入 SSE；逐项审核后检查草稿覆盖，必要时复用现有限额 WebSearch 并逐主张审查来源；AnswerGate 只能链接真实输入 ID，且引用需对应审核中已支持的主张；最终答案另做覆盖检查。无效审核、覆盖检查格式错误、最终答案证据冲突/遗漏均 fail closed。核验过程写入 `process_json.verification`，历史 API 与 SSE final 不公开该字段。答案完整持久化后才输出 SSE delta；生成期间的阶段事件仅说明状态，不含正文或推理。
- **DB/兼容**：新增迁移 `apps/backend/migrations/versions/a7c4d2e91b60_notebook_web_sources.py`，允许 `web_sources.course_id=NULL` 并增加 Notebook FK；降级发现 Notebook 来源时拒绝执行。普通课程 WebSource 仍按原课程路径查询。
- **关键变更文件**：`apps/backend/app/ai/notebook_qa.py`、`apps/backend/app/api/v1/agent.py`、`apps/backend/app/api/v1/conversations.py`、`apps/backend/app/db/models.py`、`apps/backend/app/services/conversations.py`、`apps/backend/app/web_search/service.py`、`apps/backend/app/schemas/conversations.py`、迁移与 Alembic/会话测试；前端 SSE 状态事件类型和显示更新位于 `apps/web/src/api/agentStream.ts`、`apps/web/src/api/agent.ts`、`apps/web/src/features/conversation/useConversation.ts`。
- **独立审查**：实现复审确认来源归因与 final-answer coverage 两项 P1 已修复，无剩余阻断问题。coverage 是结构化模型审议，不能数学证明语义完整；对此采用独立覆盖调用和 fail-closed。
- **最终验证**：命令 `pwsh -NoProfile -File .\scripts\test.ps1`，退出码 0；Ruff 通过；后端 448 passed / 4 skipped / 2 warnings（pytest 插件重写、Starlette/httpx 弃用）；导航测试 52 passed；Vitest 80 files / 411 tests passed；`tsc -b`、Web production build、Desktop main-process build 通过。Vite 主 bundle >500KB 警告仍存在。
- **未执行/剩余限制**：未用真实模型、真实文件或真实供应商账单验证；未做浏览器人工验收；没有用真实用户数据库。模型调用中的单次请求无法被可靠硬取消；断开后同步请求可能完成当前 provider call，但阶段边界会阻止后续阶段继续并将未发布流程保存为失败；完整答案已持久化后若 SSE 断开则消息标记 `aborted`，用户可从历史恢复完整正文。AI-02/AI-03 的真实冲突案例与真实外部源质量需后续人工验收。
- **下一批**：B1 视觉模型配置分离和图像能力预检（记录见第 12 节）。B2 预算已完成本地实现与自动回归（记录见第 13 节）；C1/C2 Workspace 统一和 D 分层拆分仍未实施。

## 12. B1 完成记录（2026-11-01，本地未提交）

- **状态**：视觉模型与文本模型配置已分离；全程 AI 页面读取使用视觉配置。当前分支 `feat/overall-inspection`，基线提交仍为 `0b0c0334faade82c4acdc719e9c0f02976d7515d`；全量改动保持本地未提交、未推送。
- **能力预检**：设置面板可用草稿 URL/Key/model/timeout 调用 `POST /api/v1/config/test-vision-capability`。请求发送随机颜色的 PNG，并要求模型报告左侧颜色；需匹配本次随机值。调用元数据有审计，不保存图像或 Key。
- **身份与凭据安全**：能力缓存索引包含 base URL、模型与凭据 HMAC 指纹。HMAC Key 在 `NOTEBOOK_DATA_DIR` 内创建，完整写入并 fsync 后 hard-link 发布；原始 Key、完整 URL 和图像均不落入缓存或 Asset 快照。环境 URL 中若含 userinfo/query/fragment 则视为无效，设置状态和处理快照不回显其内容。Worker 单次捕获运行配置，用同一份配置校验后创建视觉客户端。
- **门禁**：未通过当前视觉配置预检或缺少相应视觉/文本计价快照时，新 `llm` 文件/图片上传和已有 Asset 路线切换返回 409；执行中如配置身份不再匹配，页面读取前 fail closed。
- **独立评审**：3 个 P1（URL 凭据回显、Key 轮换复用能力证明、校验与建客户端之间的凭据竞态）已修复并复审关闭；HMAC 密钥文件半写并发问题也已用原子发布修复。风险：不支持 hard-link 的数据盘未实测；多进程并发预检可能覆盖另一配置的缓存项，但只会造成再次预检。
- **验证**：`pwsh -NoProfile -File .\scripts\test.ps1`，退出码 0；Ruff 通过；后端 455 passed / 4 skipped / 2 warnings；Web navigation 52 passed、Vitest 80 files / 412 tests passed；Web TypeScript/生产构建和 Desktop main-process 构建通过。首次全量回归的一个草稿恢复前端用例时序失败，单文件复跑通过，随后全量复跑通过。Vite 主 bundle >500 KB 警告。未调用真实视觉供应商、未做真实资料质量或浏览器人工验收。
- **下一批**：C1/C2 将课程与未分类 Notebook 的 Workspace 收敛为同一实现，再进行 D 分层整理。

## 13. B2 完成记录（2026-11-01，本地未提交）

- **状态**：新增 `FileProcessingBudget` 与 `ProviderUsageReservation` 账本，以及 Alembic 迁移 `b6e1a9d420fc`；费用按 Asset 累计并与解析重试、Worker 重启共用。limit 使用整数 fen，初始 1000 fen。
- **价格/汇率**：设置页支持文本/视觉输入输出价格、视觉每图 Token 上界、价格版本/来源、USD/CNY 汇率、日期和安全缓冲。缺价、来源格式不合规、汇率过期或不能计算上界时拒绝请求。费率由维护者按供应商公开价格录入；自动化验证只使用隔离测试中的 Fake tariff，不曾调用真实供应商。
- **预留/结算**：供应商请求发出前，以事务/CAS 原子预留最大费用；响应须含完整 usage 才能按价格与 FX 快照结算，释放差额。响应超额会登记实际 usage 并标为 `overrun`；超时、失败或 usage 缺失保留全部预留并标为 `uncertain`，后续收费请求被阻止。请求边界在 `DeepSeekClient.complete` 与直接视觉服务中；标准/全程 AI 解析、规划、正文组合和格式修复均设置 Asset/Notebook/阶段范围。普通会话及独立 WebSearch 不进入文件预算。
- **共享调用策略**：单次共享请求会对每个涉及 Asset 分别预留/记账整笔调用费用，采用保守重复计费以避免跨文件借用额度。此策略可能提前耗尽多个文件额度。上传生成结束后自动触发的知识关系收费任务已停用；用户另行显式创建的关系任务不在本文件流水线。
- **可观察性**：新增 `GET /api/v1/assets/{asset_id}/processing-budget?notebook_id=...`，Settings 返回价格配置 readiness；Notebook 资料/图片资源可显示剩余金额和耗尽、不确定、超额状态。预算代码错误以 `budget_*` 写入文件解析/生成任务，任务失败保留已完成检查点且不会自动切换 Provider/路线。
- **Fake Provider 验证**：新增 8 个预算测试，覆盖价格缺失/过期、预留结算/幂等、usage 缺失、超额、共享多 Asset、并发竞争、正常 Fake Provider usage 与超时禁止重试。另更新 SQLite migration drill、生成预算失败用例、自动关系停用及 Settings schema 测试。目标价剩余额度不足时在请求发出前拒绝；不能证明供应商最终账单在所有未知行为下绝对不超额，只保证在已配置价格、每图上界、usage 与限额假设下的本地规则。
- **验证记录**：当前全量脚本后端 Ruff 通过、463 passed / 4 skipped / 2 warnings；导航 52 用例通过。Vitest 首次全量有 3 个 Settings 用例因旧 mock 缺少新增 `budget` 字段失败，前端已加入兼容性默认值，6 个相关 Settings 用例复跑通过，Web TypeScript/production build 通过；待完整重跑全量脚本确认。Vite 主 bundle >500 KB 警告仍在。
- **未执行/限制**：未实测真实模型价、真实供应商账单/图像 Token、真实 PDF/图片质量、浏览器人工流程或真实用户数据库迁移。调用前上界依赖维护者配置准确；共享请求保守重复记账；上传触发关系分析已暂停。当前分支工作区仅本地修改，未提交、未推送。
- **下一批**：C1/C2 Workspace 统一；之后执行 D 分层重构。

## 14. C1/C2 Workspace 统一与 D 分层第一步（2026-11-01）

### C1/C2：课程与未分类 Notebook 共用页面

- **路由**：`/courses/:courseId/notebooks/:notebookId` 与 `/notebooks/unbound/:notebookId` 均渲染 `pages/NotebookPage.tsx`；兼容 URL 保留。`pages/UnboundNotebookPage.tsx` 已删除，前端代码无其他运行时引用。
- **身份契约**：新增 `features/notebook-workspace/hooks/useNotebookIdentity.ts` 与 `adapters/notebookApiAdapter.ts`。课程/未分类身份映射到相应读取、重命名、附件和历史 API；保存及草稿沿用既有 `useNotebookSave` 的 unbound 分支。AI Bridge 和打开助手事件在未分类情形传 `courseId: null`，不伪造课程 ID。
- **能力对照**：两类路由共用 Tiptap 编辑器、document JSON、revision/CAS 保存、自动保存/草稿冲突、图片附件、历史预览/恢复及 Bridge；未分类保留 SourceUploadPanel 资料上传，课程资料批量管理与回收能力仍是课程上下文专属。附件/来源资源列表与 Notebook 级预算状态来自同一共享页面编排。
- **回归**：`scripts/test.ps1` 在 D 服务抽取前退出码 0：Ruff 通过；后端 463 passed / 4 skipped / 2 warnings；导航 52 passed；Vitest 80 files / 412 passed；Web 与 Desktop 主进程构建通过。为本次统一改造更新 `notebook-history-dialog.test.tsx`，课程/未分类历史恢复与焦点用例都在共享路由页面运行。Web 构建仍有主 bundle >500 KB 警告。
- **未验收**：未执行浏览器人工验证 NB-01…NB-04 的真实页面、绑定/解绑/知识森林跳转及 PDF/图片上传过程；自动组件测试不替代人工验收。需要人工检查保存冲突、后台生成期间编辑保护和预算耗尽提示。

### D：分层拆分起步

- **确认并消除的反向依赖**：原 `services/notebook_generation_inputs.py` 在应用服务层导入 `api.v1.generation.create_generation_job`。新增 `services/generation_jobs.py` 作为生成任务 Application Service；API Router 调用该服务，上传输入编排也直接调用服务，不再从 Service 反向依赖 API。
- **行为保持**：原 POST `/notebooks/{notebook_id}/generation-jobs` 路径、Header 幂等键、错误码、状态码、校验和响应字段保持；`generation.py` 中查询/重试/取消端点仍复用同一个响应序列化器。未修改数据库和迁移。
- **验证**：Ruff 三文件通过；`pytest apps/backend/tests/test_generation_pipeline.py apps/backend/tests/test_generation_limits_db.py apps/backend/tests/test_notebook_forest_jobs.py apps/backend/tests/test_document_ir_generation_e2e.py -q`：43 passed / 1 warning。随后完整 `pwsh -NoProfile -File .\scripts\test.ps1` 退出码 0：Ruff 通过、后端 463 passed / 4 skipped / 2 warnings、Web navigation 52 passed、Vitest 80 files / 412 passed、Web/Desktop 构建通过。主 bundle >500 KB 警告仍在。
- **D 未完成项**：`api/v1/notebook.py` 仍约 1200 行，尚未按 lifecycle/documents/revisions/resources 等模块拆路由与服务；其他 API→Service→Domain 依赖边界及大前端页面职责尚未逐一审计。该工作需后续分批提取并保持 `write_document()` CAS、来源索引、资产归属和历史行为不变。

### 当前工作区和 Git 边界

- 当前分支仍为 `feat/overall-inspection`；本地 HEAD 与本轮 fetch 后 `origin/feat/overall-inspection` 均为 `0b0c0334faade82c4acdc719e9c0f02976d7515d`。本轮未创建提交，工作区包含全部待审改动。
- 所有本轮 A2/B1/B2/C1/C2/D 第一阶段差异均仅在本地未提交工作树；按用户明确要求，未提交、未推送。未改动已发布历史迁移；新迁移仅为 A2/B2 的新增版本。
- 整体计划状态：A1/A2/B1/B2 与 C1/C2 自动验证阶段已完成；真实模型/材料/账单/浏览器验收未做；D 只完成生成任务应用服务下沉的第一步，不能标记为整体完成，ADR-0002 继续 Proposed。
