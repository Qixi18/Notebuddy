# 后端调用与业务数据存储契约

本文记录当前 `main` 的本地 Web 实现，供首页与知识树、答疑 Agent、课程与笔记三条开发线共同使用。字段及错误响应以 `apps/backend/app/schemas/` 和 `apps/backend/app/api/v1/` 为准；详细接口见 [API 契约](api.md)。云端多用户部署不属于当前实现。

## 共同调用规则

- 前端通过 `apps/web/src/api/` 的封装调用 `/api/v1`。开发时 Vite 将 `/api` 代理到本地 FastAPI；路由在 `apps/backend/app/api/v1/routes.py` 汇总，并由 `apps/backend/app/main.py` 挂载。页面和组件不能直接读写 SQLite 或 `data/` 文件。
- 后端路由负责请求校验和 HTTP 响应，业务规则在服务层，持久化模型在 `app/db/`。改接口时同步更新后端 schema、前端 API 类型和调用方、迁移与文档。
- 以 ID 和服务端校验确定归属：知识树叶子指向稳定的 `Note.id`；课程、笔记本、讲次、笔记与会话请求须校验所属课程。已软删除的课程或讲次不作为正常内容或答疑来源。
- 笔记保存携带 `expected_revision_number`；笔记本目录重排、续读位置和森林课程配置使用各自的预期修订号。收到 409 后刷新数据并处理冲突，不直接覆盖。
- `POST /courses/{course_id}/materials` 保存原文件并登记持久任务。独立的 `app.workers.runner` 执行解析；页面通过任务接口查询结果。森林培养方案与跨课程关系候选任务也由该执行器处理。

## 三条开发线的调用链

以下路径均以 `/api/v1` 为前缀。请求体、返回类型和兼容接口见 [API 契约](api.md)。

| 开发方向 | 读取 | 写入或异步动作 | 约束 |
| --- | --- | --- | --- |
| 首页与知识树 | `GET /courses`、`GET /forest`、`GET /forest/courses/{course_id}/tree`、`GET /forest/search`、`GET /forest/relations` | `POST /courses/{course_id}/visit`、`PATCH /forest/courses/{course_id}`、培养方案导入与关系审核接口 | 森林目录是课程、笔记本和笔记的视图；不另存笔记正文。只有实际打开课程才调用 `visit`。 |
| 课程与笔记 | 课程的笔记本、讲次、资料接口；`GET /notes/{note_id}`、来源及版本接口 | 课程和笔记本写入、资料上传、`PATCH /notes/{note_id}`、续读位置、建议审查 | 多本课程上传需明确 `notebook_id`；笔记保存带预期版本。目录不含正文。 |
| 答疑桌宠与悬浮 Agent | 课程会话列表、`GET /conversations/{id}/messages`、当前课程及笔记上下文 | 创建课程会话，再 `POST /conversations/{id}/agent-messages` 读取 SSE；传统问答见 `POST /courses/{course_id}/assistant` | 会话限定单课程；材料和阅读笔记 ID 须属于该课程。AI 改笔记先产生可审查建议。 |

前端封装主要在 `apps/web/src/api/courses.ts`、`forest.ts`、`notebook.ts`、`notes.ts`、`conversations.ts`、`agent.ts`、`agentStream.ts`。SSE 用流式客户端读取，不能用只解析 JSON 的 `request<T>`。404 表示目标或归属无效，409 常用于修订冲突或重复提交，422 用于请求校验；具体错误以对应路由为准。

## 存储地址与数据归属

`apps/backend/app/core/config.py` 把 `NOTEBOOK_DATA_DIR` 解析为绝对路径；默认是仓库根目录的 `./data`，相对配置也以仓库根目录为基准。运行时数据不提交 Git。

| 数据 | 当前持久化位置 | 主要模型或说明 |
| --- | --- | --- |
| 课程、笔记本、讲次元数据与续读位置 | `<NOTEBOOK_DATA_DIR>/notebook.sqlite3` | `courses`、`notebooks`、`materials`、`notebook_reading_positions` |
| 笔记正文、版本、来源映射和建议 | 同一 SQLite | `notes.content_markdown`、`note_revisions`、`note_source_mappings`、`source_refs`、`note_suggestions`；正文不是独立 Markdown 文件 |
| 课程内知识结构 | 同一 SQLite | `knowledge_nodes`、`knowledge_edges`；笔记通过 `knowledge_node_id` 关联概念 |
| 森林配置、培养方案、跨课程关系和任务 | 同一 SQLite | `forest_course_profiles`、`curriculum_imports`、`cross_course_relations`、`forest_jobs`；树叶使用已有笔记 ID |
| 答疑会话、用户提问、助手回答和证据 | 同一 SQLite | `conversations`、`conversation_messages`、`message_evidence`；两种会话传输共用这些表 |
| 课件与培养方案原文件 | `<NOTEBOOK_DATA_DIR>/originals/` | 数据库记录 `stored_filename` 等元数据；服务端按配置目录访问文件 |
| 派生目录、备份和检索索引 | `<NOTEBOOK_DATA_DIR>/derived/`、`<NOTEBOOK_DATA_DIR>/backups/`；`retrieval_chunks` 在 SQLite | 检索索引可重建，不承载用户笔记正文的业务真相 |
| 知识树视口与页面快照 | 浏览器 `sessionStorage` | `apps/web/src/features/tree/snapshot.ts`；只是视图状态，不是业务数据 |

表结构由 `apps/backend/migrations/` 的 Alembic 迁移管理。新增持久字段或表应提供迁移并验证旧库升级，不以删除本地数据库代替迁移。课程与资料删除遵守现有软删除和检查点流程。

### 对话历史的写入与读取

- 创建会话：`POST /courses/{course_id}/conversations` 在 `conversations` 保存课程 ID、标题和时间。`GET /courses/{course_id}/conversations` 只列出该课程的会话；会话所属课程已删除时不可继续读取。
- 普通会话答疑 `POST /conversations/{id}/messages` 与 Agent 流式答疑 `POST /conversations/{id}/agent-messages` 都先保存用户提问，再生成回答。回答完成后保存助手正文和证据映射；生成失败时保留用户提问并保存 `status=failed` 的助手消息。Agent 的 `step`、`delta` 等 SSE 中间事件不写为历史消息。
- `GET /conversations/{id}/messages` 从数据库读取双方消息，并通过 `message_evidence` 还原来源卡片。前端刷新或重开页面后从该接口恢复历史；浏览器状态不能替代后端历史。
- 客户端应为发送动作提供 `idempotency_key`。普通会话端点对已完成的重复请求可返回原回答；Agent 流式端点对重复键返回 409。不要把重试生成当作新增用户问题。
- 独立的 `POST /courses/{course_id}/assistant` 返回单次回答，不创建会话消息。需要连续追问、历史恢复或桌宠共享会话时，使用上述会话端点。
- 当前历史正文保存在本地 SQLite，可能包含用户输入和模型回答。不要将数据库、备份或真实会话文本加入 Git、日志及测试样例；云端多用户存储与访问隔离须另行实现。

## 并行开发边界

- 三个分支从同一个已确认的 `main` 提交建立。各工作区使用独立的 `NOTEBOOK_DATA_DIR` 和端口配置，避免不同实例同时写同一 SQLite。修改 Vite 代理时核对后端地址和 CORS。
- 涉及共享模型、schema、API 路径或语义的变动，应先统一契约再同步各分支；不要在各分支建立重复的课程、笔记或知识树数据源。
- 当前实现面向本地单用户工作区。云端持久化、身份和用户隔离需要单独实施与验证。

实现入口：`apps/backend/app/core/config.py`、`app/db/models.py`、`app/db/forest_models.py`、`app/api/v1/routes.py`；运行、迁移和备份见 [运维](operations.md) 与 [迁移](migrations.md)。
