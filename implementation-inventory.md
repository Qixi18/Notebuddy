# NoteBuddy 核心架构整改实施盘点

盘点日期：2026-11-01（Asia/Shanghai）

规划依据：`Notebuddy开发与ChatGPT的交流信息/2026-11-01-Notebuddy-Codex-核心架构整改开发规划.md`

盘点基线：`origin/feat/overall-inspection`，执行时 `git fetch origin` 后 HEAD=`67677dd8771f2fe756d2f29a986102a64655a730`

本盘点所在工作区：`feat/overall-inspection`，HEAD 与上述远端基线相同。
状态定义：**确认存在**=在该基线源码中定位到；**已消失**=在约定搜索范围中核实不存在；**未确认**=仅凭静态源码不能确定，需运行态或更深入验证。

> 本文仅记录源码、路由、测试和迁移现状，不代表规划功能已经实现或验收。调查未读取本地 `.env`、用户真实数据库或上传材料；未执行迁移、真实供应商调用或浏览器人工验收。

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
