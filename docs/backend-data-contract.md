# 后端调用与业务数据契约

本文描述本地 `feat/debug-integration` 当前实现，核对基线为 2026-10-30 本地 `0777d0e`（Fetch 时 origin 为 `4759ff5`）。云端多用户安全不在当前本地实现保证范围内。字段和错误以 `apps/backend/app/schemas/`、路由及服务源码为准。
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

Notebook 页面从 document API 读 JSON 与 revision，编辑器提交预期版本；未知/不可渲染节点及数学错误的具体表现由当前编辑器组件负责，真实浏览器边界仍待验收。`NotebookSection` 由 `document_json` 重建，供树、搜索、阅读位置等定位；稳定 block ID 用于锚定正文。

知识森林读课程/Notebook 及目录和关系，不另存正文。Agent 服务端工具按会话课程及可选 Notebook 范围加载现有正文、目录、已处理资料和证据；上传解析流程由后台任务处理，Agent 不应重复解析，也不应把浏览器临时内容当作权威。来源和范围须由服务端校验。

## 备份、迁移与安全

本地默认 SQLite 位于 `<NOTEBOOK_DATA_DIR>/notebook.sqlite3`，原始资源位于数据根目录管理的存储路径。备份应保留 Notebook 正文、revision、来源映射、资产和历史可读性；恢复先预览并恢复到隔离目录。迁移只在隔离库验证升级、重复执行和恢复，不得触碰用户真实库。运行时数据库、原始文件、`.env`、密钥和真实会话不得提交。

详见 [架构说明](architecture.md)、[API](api.md)、[解析说明](parsing.md)、[迁移与恢复](migrations.md) 和 [验收矩阵](acceptance.md)。
