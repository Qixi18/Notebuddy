# 后端调用与业务数据契约

本文的既有契约段落记录本地 `feat/debug-integration` 历史快照（2026-10-30）；2026-11-01 的整改审查基线为 `origin/feat/overall-inspection` @ `67677dd8771f2fe756d2f29a986102a64655a730`。云端多用户安全不在当前本地实现保证范围内。字段和错误以对应基线的 `apps/backend/app/schemas/`、路由及服务源码为准。下列整改目标为 Proposed，不应误读为已实现契约。

## Notebook 答疑整改提案（Proposed；A1 部分已实现）

- 目标范围固定为一个明确的 Notebook 或用户明确选择的课程；不得静默退化为全局跨课程检索。
- Notebook 第一来源是所选 Notebook 当前已保存 `document_json` 与 revision。核验材料限于该 Notebook 有效 `NotebookAsset` 关联的当前完成 ParseRun；来源不完整时不得扩大到其他 Notebook 或课程文件。
- 核验前的草稿不向客户端发送正文 delta，也不向用户暴露内部推理。只有完成主张核验和证据 ID 校验后才允许流式发送最终回答。
- 新会话目标使用 `notebook_id`；`course_id` 可空仅表示 Notebook 级范围。历史 `scope='note'` 的读取映射必须显式兼容，不得依据最近访问课程猜测归属。
- 本轮 Agent 不创建 Notebook 编辑建议；既有 `NotebookEditSuggestion` 和 Note 历史数据/迁移留存，旧写回入口在兼容风险核查后关闭。

### A1 当前代码契约

- Alembic `f2b7d9a1406c` 增加 nullable `Conversation.course_id`、nullable `notebook_id` 和 `scope='notebook' => course_id IS NULL` 约束；Notebook 删除后目标 FK 设为空，消息历史保留。降级遇到任何 Notebook-scope 会话会拒绝。
- `POST/GET /api/v1/notebooks/{notebook_id}/conversations` 创建/列出指定 Notebook 会话。新行使用 `scope=default_scope='notebook'`、`notebook_id=<真实 ID>`、`course_id=null`，不随 Notebook 绑定状态变化。
- 通用 `GET /api/v1/conversations/{id}/messages` 可读该历史。普通消息和 Agent 消息暂时返回 409；不得用课程检索或最近课程兜底。专属答疑服务属于 A2。
- 旧 `scope='note'` 和 `note_id` 字段仍用于兼容历史。旧标识若能同时解析到不同 Notebook、跨课程、已删除或不可解析，不自动映射；历史消息仍可读。
- 当前 Agent 工具表不暴露正文编辑建议。AssistantPage/Dock 不再发送 `reading_context.note_id`，Dock 也不提供直接把回答写入正文的入口。历史建议表、API 和迁移保留。

Notebook→DocumentIR→WebSearch→核验后 SSE 的实现进度见后续 A2 记录；整体整改 ADR 仍为 Proposed。

## B1 视觉模型配置和预检（本地实现、全量回归与复审已完成）

- `NOTEBOOK_VISION_BASE_URL`、`NOTEBOOK_VISION_MODEL`、`NOTEBOOK_VISION_TIMEOUT_SECONDS` 和 `NOTEBOOK_VISION_API_KEY` 独立于文本模型配置。设置面板的预检使用当前草稿值，不要求先保存。
- `POST /api/v1/config/test-vision-capability` 向配置的 OpenAI-compatible `/chat/completions` 发送小型已知红蓝图像，要求模型识别图片左侧颜色；仅返回能力结果和模型元数据，API Key 不进入审计 metadata。
- 能力结果缓存到 `<NOTEBOOK_DATA_DIR>/vision-capabilities.json`，以规范化 base URL + model 的 SHA-256 指纹索引，只存布尔结果和检查时间，不保存 Key、URL 或图片。改模型或地址后指纹改变，需重新预检。
- 新建 `llm` 上传、图片上传及已存在 Asset 切换到 `llm` 路线前都要求当前配置已验证；未验证返回 409。处理快照固定非敏感视觉模型身份及能力指纹。读页 Worker 再核对快照指纹和能力缓存，实际调用独立的视觉 Provider Client；校验失败在任何页面图片模型请求前终止。
- `standard` 路线仍可使用本地 OCR/可选视觉增强；B1 不提供文件处理费用上界。按 Asset 原子预留、重试/恢复累计、价格快照以及 10.00 CNY 硬预算属于 B2，当前不可声称付费调用受到统一预算保护。
- 当前自动化只覆盖 Fake Provider 和临时测试数据；真实模型预检会产生一次外部请求，尚未执行真实供应商/视觉质量或浏览器人工验收。
## 双路线处理补充（2026-10-30）

`assets.processing_route` / `processing_config_json` 固定上传所选路线和非敏感模型连接身份，`materials.processing_route` 与其保持一致。批次保存初始路线；失败输入切换后可在同一批次中按实际路线分组生成。历史数据默认 `standard`，新上传的默认值由设置控制。

`processing_steps` 保存以 scope/stage/step_key/fingerprint 唯一定位的成功模型步骤和用量，供读取、规划、正文与关系任务续跑，不承载 Notebook 正式正文。页面图像保存在 `derived/pages/<asset>/<run>/`；完整读取才提升为当前 Document IR。正文仍通过原有 Notebook 文档、来源映射、修订号与派生小节索引写入。

`notebook_generation_jobs.relation_job_id` 跟踪正文提交后的独立藤蔓任务。用户删除联系时在 `notebook_relation_suppressions` 保留端点决定，自动分析不得恢复该条联系；人工联系也不会被自动关系覆盖。迁移为 `a5e3c8d1f209_dual_processing_routes`，使用 Alembic 升级，不删除现有业务数据。

以上路线补充来自解析分支，本文其余部分以本地 `feat/debug-integration` 的 DocumentIR 与 Notebook 正文契约为准。

## 权威数据流

```text
Notebook
  └─ Asset / Notebook 资源登记与持久上传批次
      └─ Document Processing 与 DocumentParseRun
          └─ 版本化 DocumentIR、来源位置和质量状态
              └─ 生成任务快照、质量门禁和 revision/CAS 合并
                  └─ Notebook.document_json（唯一正式可编辑正文）
                      ├─ 编辑器读取、保存、历史版本与恢复
                      ├─ NotebookSection 章节目录/文本投影
                      ├─ retrieval_chunks 等检索派生数据
                      ├─ 知识森林读取课程、Notebook、目录及关系
                      └─ Agent 在课程/Notebook 范围内读取正文和证据
```

当前主验收重点是 PDF、JPG、PNG；代码仍保留其他支持格式的兼容能力。具体白名单由 `GET /api/v1/config/capabilities` 与上传校验决定，不能仅由本段推断。

| 对象 | 职责 | 正式正文？ |
|---|---|---|
| `Notebook.document_json` / `document_revision` | Tiptap/ProseMirror 正文及并发版本 | **是，唯一权威源** |
| `NotebookDocumentRevision` | 正文版本快照、来源标记和保留策略 | 历史快照，不是独立当前源 |
| `DocumentIR` / `DocumentParseRun` | 来源文件的解析版本、结构、位置、质量结果 | 否 |
| `NotebookSection` | 从正文重建的目录和文本投影 | 否，可重建 |
| `retrieval_chunks`、森林树/搜索数据 | 检索或导航派生索引 | 否，可重建/同步 |
| 旧 `Note.content_markdown` / `NoteRevision` | 迁移、兼容、审计和历史引用；新旧读写边界依路由而异。前端仍调用的旧 NoteSuggestion API 在本轮路由审计中未找到后端注册，须单独核实 | 否，不得作为新正文源 |
| `NotebookGenerationCandidate` | 非当前主要生成写入链；`notes/assets.py` 仍检查 pending 候选的附件引用，避免资源过早清理 | 否；清理前须审计历史行与资源保护 |
| `NotebookEditSuggestion` | 对现有正文的待审修改及基准 revision | 否；必须通过审查/受控应用 |

单一正文源不意味着删除来源、资产、历史版本或派生表。不要删表或改已发布 Alembic migration。

## 代码核对状态

| 主题 | 代码核对 | 自动/真实证据 |
|---|---|---|
| Notebook 正文和版本 | `app/db/models.py`、`app/notes/store.py`、`app/api/v1/notebook.py`：JSON、revision、版本快照及 CAS 写入 | 有相关自动测试；当前全量回归尚未执行 |
| 章节派生索引 | `app/notes/index.py`：由 document 重建 | 有服务测试；索引不作为写入源 |
| 资料解析 | `app/api/v1/materials.py`、`app/document_processing/`、Asset/ParseRun 模型 | 结构经代码核对；真实材料质量未在本次核实 |
| 生成 | `app/api/v1/generation.py`、`app/generation/context.py`、`app/workers/notebook_generation_worker.py` | 任务快照、质量检查、revision 合并由代码核对；真实模型质量待验证 |
| Agent 与森林 | `app/api/v1/agent.py`、`app/ai/agent_read_tools.py`、`app/forest/`、`app/notes/index.py` | 范围与读取路径代码核对；真实模型与完整浏览器体验待验证 |
| 旧 API/迁移兼容 | `app/api/v1/materials.py`、`notes`、迁移模块及旧模型仍存在 | 具体调用面见 [API](api.md)；外部调用方覆盖待验证 |

## 路由与写入边界

路由在 `app/api/v1/routes.py` 注册 `materials`、`notebook`、`generation`、`agent`、`forest` 等模块。主要路径包括：

- `GET/PUT /api/v1/courses/{course_id}/notebooks/{notebook_id}/document`：读取/写入正文；请求带 `expected_revision`，陈旧写入返回冲突，不应静默覆盖。
- `GET/PUT /api/v1/notebooks/unbound/{notebook_id}/document`：无课程绑定 Notebook 的对应正文路径。
- `POST /api/v1/notebooks/{notebook_id}/assets`：登记 Notebook 上传资源；`POST /api/v1/notebooks/{notebook_id}/upload-batches/{batch_id}/complete` 及对应 `GET` 状态路径：完成上传批次并查询处理状态。
- `GET /api/v1/assets/{asset_id}/document` 与 `/document/runs/{run_id}`：读取当前或指定解析版本；ParseRun 与 Asset 关联，DocumentIR 保存在解析运行结果中。
- `POST /api/v1/notebooks/{notebook_id}/generation-jobs`：创建持久生成任务；同组 GET、`/{job_id}`、`retry`、`cancel` 管理任务。
- 森林、会话、Agent 与传统课程/资料/Note 路径见 [API 契约](api.md)，均以路由源码为准。

上传入口为 Notebook 资源 API；Asset、NotebookAsset、Material 及批次/任务记录维持资源归属与异步状态。传统 `POST /courses/{course_id}/materials` 仍由 `materials` 路由注册，属于保留的兼容路径。图片附件走 Notebook attachment/asset 路径；实际支持类型与限制由 capabilities、上传校验和设置决定。

## 生成与冲突保护

上传后初始/增量生成通过 `NotebookGenerationInput` 追踪每个 Asset 的幂等和恢复状态。Worker 使用持久化 ParseRun/DocumentIR 快照，先检查解析质量与来源；生成后验证结构、公式及引用，再按任务保存的 `base_document_revision` 对当前正文合并。revision 已变化时须处理冲突，不能覆盖用户新编辑。任务状态、重试和取消由持久 API/Worker 管理。实现声称的具体质量门禁以 Worker 与 generation/context 代码为准；本契约不声称真实模型输出已验收。

失败任务的“未部分写入”行为应以事务边界和自动测试确认；不能从文档推定。若需要修改，应补测试覆盖截断、公式/表格/图片节点、无效来源、重试幂等、用户并发编辑和失败回滚。

## 前端、森林和 Agent

提问人设由单次答疑、普通会话和 Agent 流式请求共用的 `TeacherPersonaId` 校验：当前值及默认值均为 `vodyanitsa`，历史 `elf` / `doubao` / `feiyu` 在请求边界归一为当前角色，未知值拒绝。此兼容不迁移历史会话或修改数据库结构。

Notebook 页面从 document API 读 JSON 与 revision，编辑器提交预期版本；未知/不可渲染节点及数学错误的具体表现由当前编辑器组件负责，真实浏览器边界仍待验收。`NotebookSection` 由 `document_json` 重建，供树、搜索、阅读位置等定位；稳定 block ID 用于锚定正文。

知识森林读课程/Notebook 及目录和关系，不另存正文。Agent 服务端工具按会话课程及可选 Notebook 范围加载现有正文、目录、已处理资料和证据；上传解析流程由后台任务处理，Agent 不应重复解析，也不应把浏览器临时内容当作权威。来源和范围须由服务端校验。

Notebook 专属答疑走 `app.ai.notebook_qa.run_notebook_answer`：服务端用会话绑定的 `notebook_id`、当前 `document_revision` 和 `Notebook.document_json` 建立正文证据，再仅从该 Notebook 当前、已完成且未解绑的 owner `NotebookAsset`/ParseRun 检索 DocumentIR。正文初稿、逐主张核验、来源补充审核、最终答案和 AnswerGate 都在服务端缓冲；核验前 SSE 仅发送阶段状态，不发送正文增量。最终主张只可关联通过白名单校验的正文/DocumentIR 块和 WebSource；未分类 Notebook 的 WebSource 以 `notebook_id` 归属且 `course_id=NULL`。普通 JSON 与 Agent SSE 入口共用同一核验服务和证据映射 helper。内部核验记录写入消息过程 JSON，但历史 API 与 SSE final 会剔除 `verification` 字段。审核输出无效、覆盖检查失败、答案 Gate 遇到冲突或上下文快照变化时不会将草稿作为成功答复发布。

## 备份、迁移与安全

培养方案保持独立的 `CurriculumImport` → `ForestJob` → 预览确认流程，不生成 Notebook/DocumentIR。课程代码、学分（0–100）、学时（0–10000）与必选修保存在导入 `rows_json`；仅学期、层级、先修写入森林 profile。已关联课程必须提交 `expected_profile_revision`，旧预览 GET 会补充当前版本；缺失或过期确认返回409，任何错误回滚整批。

任务 `source_snapshot_json` 冻结处理路线、非敏感模型身份和原文件/文本哈希；成功读页与最多40行/约12000字符的提取批次复用 `ProcessingStep`。每次 Worker 最多新增3步后让出，失败重试保留进度，旧任务默认标准路线。模型必须引用该批来源，学分/学时/必选修须有对应表头证据；不推测培养要求。

确认快照保存新建/已有映射及 profile 修改前后属性与 revision。撤销先备份，再在写事务内重查版本；恢复属性会继续递增 revision。新建课程仅在未改名、描述、无 Notebook/历史内容/会话等引用且未使用时软删除。确认后有后续修改则整批拒绝；旧已确认记录无快照时不提供撤销。该功能无数据库结构迁移，课程附加信息暂不作为跨方案的全局课程字段。

本地默认 SQLite 位于 `<NOTEBOOK_DATA_DIR>/notebook.sqlite3`，原始资源位于数据根目录管理的存储路径。备份应保留 Notebook 正文、revision、来源映射、资产和历史可读性；恢复先预览并恢复到隔离目录。迁移只在隔离库验证升级、重复执行和恢复，不得触碰用户真实库。运行时数据库、原始文件、`.env`、密钥和真实会话不得提交。

详见 [架构说明](architecture.md)、[API](api.md)、[解析说明](parsing.md)、[迁移与恢复](migrations.md) 和 [验收矩阵](acceptance.md)。

## 文件处理预算（B2）

`FileProcessingBudget` 按原始 `Asset.id` 累计，使用 CNY fen，标准/全程 AI 的付费解析及后续 Notebook 正文生成共用同一额度。账本不设指向 Asset 的 FK，以便保留费用审计；Notebook 归属在预留时校验。`ProviderUsageReservation` 记录 call ID、Asset、阶段、任务/检查点、供应商/模型、价格版本、FX/价格快照和预留/结算金额。

所有付费非流式模型调用必须先用保守输入、输出及图像 Token 上界完成原子预留。调用成功且供应商返回完整 prompt/completion usage 时结算并释放差额；调用失败、超时或 usage 缺失保留未结算额度并将文件置 `uncertain`，不自动重试/退款。超过预留的实际 usage 标 `overrun`。余额不足、价格缺失、FX 日期超过 30 天或来源/模型配置不合规时不发起请求，错误码通过 Worker 任务暴露为 `budget_*`。供应商最终账单可能偏离本地 usage/维护者配置的计价规则；本契约只保证配置假设下的本地 1000 fen 闸门。

共享一次调用会把整笔保守费用计到每个相关 Asset，允许保守高估，不允许事后按结果不透明分摊。上传完成后自动触发的收费关系任务暂时关闭；普通对话、单独网页搜索和显式发起的关系任务不属于本文件账本。可通过 `GET /api/v1/assets/{asset_id}/processing-budget?notebook_id=...` 查询金额、状态与预留明细；设置 API 的 `budget` 暴露脱敏价目 readiness 与快照元数据，不含密钥。
