# Notebook 答疑会话兼容与迁移设计（A1 提案）

- 状态：Proposed；原设计已审查，A1 代码已落地到工作区，待本轮实现评审与完整回归
- 原设计基线：`feat/overall-inspection` @ `67677dd8771f2fe756d2f29a986102a64655a730`
- 依据：ADR-0002 和用户指定的 2026-11-01 核心架构整改规划

## 1. 已确认的现状

- `Conversation.course_id` 当前为非空 `courses.id` 外键；`load_conversation()` 要求课程存在；普通消息和 Agent API 均用该字段查询权限/资料。
- 新会话通过 `POST /courses/{course_id}/conversations` 创建，历史通过 `GET /courses/{course_id}/conversations` 列出；消息路由按 conversation ID 读取/发送。
- `scope` 当前为 `course | global | note`；`note_id` 字段在近年的 Notebook 集成中有时承载 Notebook ID，但历史数据也可能是真实旧 Note ID。
- `NotebookDocumentContext` 要求 course_id、notebook_id、revision；Agent API 明确拒绝带 note_id 的旧 `reading_context`。
- Web 前端仍有基于旧 Note 的 suggestion hook/UI；后端统一 API router 未注册旧 `/notes/.../suggestions` 路由，前端调用代码存在不等于服务端端点可用。

## 2. 建议的目标数据契约

保留现有课程/全局会话契约；给新 Notebook 会话增加独立目标，不复用 `note_id`：

```text
Conversation
  id
  course_id       nullable，旧课程/全局会话继续保留原值
  notebook_id     nullable，新 Notebook 会话目标
  scope           course | global | notebook | note（历史兼容）
  note_id         nullable，仅旧 scope=note 的历史快照，不作为新写入目标
  note_title      nullable，历史标题快照/兼容展示
```

- 新建 Notebook 会话统一使用 `scope='notebook'`、`notebook_id=<Notebook.id>`、`course_id=NULL`。这样 Notebook 绑定/解绑不需要搬迁会话归属，未分类 Notebook 不需要伪造课程 ID。
- 该会话的授权对象是精确 Notebook；解析 Notebook 时检查存在、未软删除，并只通过其真实 `NotebookAsset` 关联读取源文件。若该 Notebook 当前绑定课程，可在受限的 Notebook 服务内部读取真实 `course_id` 供来源展示；不得据此打开整门课程范围检索工具。
- 课程范围仍使用 `scope='course'` 和必填的真实 course_id。跨课程 `global` 只能由用户显式选择并使用其现有会话语义；不作为新建默认值。
- 旧 `scope='note'` 行保持原字段不改写。读取时检查 `note_id` 是否匹配同 course 的 Notebook ID，以及是否匹配同 course 的旧 `Note.notebook_id`。若仅一条有效且归属一致则解析；若两者都命中同一个 Notebook 可安全解析；若两者命中不同 Notebook、出现跨课程/软删除目标或无法唯一解析，则作为歧义拒绝继续提问，但历史消息仍可读。不得用简单优先级掩盖跨表 ID 冲突。

## 3. API 兼容

- 保留 `POST/GET /courses/{course_id}/conversations`，只创建/列出 course/global 会话；其中旧 note 会话仍为历史兼容读取结果，不再新建。
- 新增 `POST/GET /notebooks/{notebook_id}/conversations`，创建/列出 Notebook 专属会话；会话响应 `course_id` 允许为 `null`，增加 `notebook_id`。通用消息读取/发送端点继续接受 conversation ID，但按该会话的真实 scope 做授权。
- 新请求 `AgentMessageCreate.scope` 增加 `notebook`，Notebook 身份使用 `notebook_context.notebook_id`；`notebook_context.course_id` 改可空或移除为权威字段。不能同时相信客户端提交的 course_id 与数据库归属。
- 对 `scope='notebook'`，工具只包含 Notebook 正文读取、限定 Asset 的 DocumentIR 核验和（A2 阶段）显式受限 WebSearch；隐藏课程检索、全局森林、出题/课程分析等会扩张范围的工具。A1 先停用正文编辑建议工具，A2 再按证据协议建只读工具集。
- 新前端必须将未分类 Notebook 创建/列出会话走 notebook URL；不能把 `null` 替换成最近课程 ID。旧客户端仍可访问课程 API 和历史 scope。

Notebook-scope 答案不得流经要求有效 Course 的旧普通答疑实现。其 A2 答案持久化须以 Notebook 证据（`MessageEvidence.notebook_id`、正文 revision / DocumentIR ParseRun）为主；WebSource 若 schema 仍要求 course_id，则必须定义 Notebook 会话的安全 owner/归属或调整来源关联，不能给未分类会话伪造课程。未分类会话反馈不得调用 course-only `/courses/{id}/feedback`，需明确禁用或新增 Notebook 会话反馈契约。

## 4. Alembic 迁移草案

基于当前唯一 head `f1a7c9d3e620` 新增迁移，不修改任何已发布 migration：

1. `conversations.course_id` 改为 nullable，保留 `courses.id ON DELETE CASCADE`，以支持 SQLite 的 `batch_alter_table`。
2. 新增 nullable `conversations.notebook_id VARCHAR(36)`，外键指向 `notebooks.id ON DELETE SET NULL`；新增索引 `ix_conversations_notebook_id`。
3. 保留 `note_id`、`note_title`、所有现有行、消息、证据、唯一 idempotency 约束。对历史数据不执行猜测性回填。
4. 对 `scope='course'`、`scope='global'`、`scope='note'` 的既有值与原 course_id 不做改写；新增 DB `CHECK` 保证 `scope='notebook' => course_id IS NULL`。创建新会话时由 API/service 额外保证 `notebook_id` 指向有效 Notebook；Notebook 被永久删除后外键会将其置空，行保留为只读历史。任何失去有效 Notebook 目标的 notebook-scope 会话都只能读历史，继续提问返回明确不可用错误。
5. downgrade 删除新增索引/约束/列，再将 `course_id` 改回 not-null 前，**只要存在任意 `scope='notebook'` 会话**就明确中止 downgrade 并提示先导出/清理新型会话；不能仅检查 NULL course_id，也不得用最近访问课程回填。

迁移验证需在临时 SQLite 数据库进行：从 `f1a7c9d3e620` 升级、检查旧 course/global/note 行及消息/证据不变、创建并读取 course-bound/unbound Notebook 会话、外键行为及 downgrade 对新型会话的保护。必须另外用项目 Alembic drill 工具覆盖 SQLite batch migration；不连接任何本地真实库。

## 5. 依赖代码与测试

- 后端：`app/db/models.py`、`schemas/conversations.py`、`api/v1/conversations.py`、`api/v1/agent.py`、`api/v1/shared.py`、`services/conversations.py`、Agent scope/tool gating。
- 前端：`api/conversations.ts`、`api/agentStream.ts`、`features/conversation/useConversation.ts`、`AssistantPage.tsx`、`AssistantDock.tsx`；Notebook 选择必须来自 Notebook API，而不是 `Note` 列表。
- 测试：扩展 `test_conversation_scope.py`、`test_conversation_manage.py`、`test_agent_notebook.py`、`test_agent_tool_scope_gates.py`、迁移 drill；扩展 `assistant-notebook-scope.test.tsx`、`agent-conversation-scope.test.tsx`、`use-conversation.test.tsx`。
- 在代码批次中建立 schema/API 可空性、跨 Notebook 越权拒绝、旧 Note ID 无歧义映射、会话范围锁定、idempotency 和服务中断测试。

## 6. 主要风险与验收判据

- `course_id` nullable 会影响所有当前假设课程必定存在的消息执行、消息审计、WebSource 保存、反馈归属、搜索和 UI 历史列表；须逐处改成 scope-aware，不能用 `or recent_course_id` 修补。
- 已定位并纳入逐项迁移清单：`services.conversations.load_conversation()` 当前强制加载有效 Course；普通消息 `api/v1/conversations.send_message()` 调用 `ensure_course`、`material_in_course`、`run_answer(course_id/course_name)`；`api/v1/agent.send_agent_message()` 强制 `ensure_course` 并调用 `run_agent`；`services.conversations.persist_assistant_message()` 按 `conversation.course_id` 过滤 `SourceRef` 与 `WebSource`；`api/v1/feedback.py`、`services/feedback.py` 及会话消息反馈端点按 course_id 校验；课程历史/搜索仅按 `Conversation.course_id` 查询。
- Notebook scope 必须在上述路径中分支：只允许 Agent Notebook 应用服务；普通课程 `run_answer` 拒绝 notebook scope；feedback 要么为 notebook 会话显式禁用，要么另加不依赖 course_id 的目标校验；持久化只关联实际存在的 Notebook/ParseRun/WebSource，不能把 `None` 传给仍假设字符串的旧路径。
- `ON DELETE SET NULL` 之后旧会话可保留消息但失去 Notebook 写入/检索上下文；该结果符合“历史仍可读，不能猜目标”。
- 全局会话的明确入口可以保留，但新用户状态不得默认选 `global`。
- A1 验收：新增 Notebook 会话没有虚构 course_id；Notebook A 会话无法打开 Notebook B 或课程资料；旧历史按真实关系只读映射；读写入口不再创建 NoteSuggestion；助手问答不改变正文 revision。

## 7. A1 当前实施记录

- 新增迁移 `f2b7d9a1406c`：`Conversation.course_id` 可空、添加 `notebook_id` 外键（Notebook 删除时 `SET NULL`）、索引及 `scope='notebook'` 无课程约束；降级遇到任何 Notebook 会话会停止。
- 新增 `POST/GET /notebooks/{notebook_id}/conversations`。新会话固定 `scope='notebook'`、真实 `notebook_id` 和 `course_id=NULL`；普通课程会话接口未改。
- Notebook 路由加载会话历史时不使用最近课程；Notebook 普通/Agent 问答暂时以明确 409 拒绝，等待 A2 专属问答服务，避免误进课程检索链。
- 旧 `scope='note'` 的历史会话保留原字段；跨 Notebook/旧 Note ID 冲突、跨课程、已软删除或不可解析的映射不会被猜测。列表映射只影响返回对象，不提交历史改写。
- AssistantPage/Dock 已移除旧 Note picker、`reading_context.note_id` 发送和正文插入/替换入口；Agent 工具注册不再暴露 `propose_notebook_edits`，Notebook scope 工具表仅有锁定 Notebook 的读取工具。
- 自动验证：后端隔离 SQLite 会话/迁移测试、前端 scope/Dock/hook 测试、TypeScript 与 Vite 构建已跑；完整 `scripts/test.ps1` 仍待本批结束前运行。迁移没有连接真实 `data/notebook.sqlite3`。
- 当前未完成：Notebook Agent 端点暂不回答；AssistantPage 只提供课程/显式全局范围，Notebook 问答入口在 Notebook Dock；A2 需补正文→当前 DocumentIR→必要 WebSearch→验证后 SSE 及专属证据持久化。

本设计与 ADR 仍为 Proposed；如果实现中发现外键删除、反馈审计或历史读取要求与本提案冲突，需修订设计并重新评审后再迁移或接受。
