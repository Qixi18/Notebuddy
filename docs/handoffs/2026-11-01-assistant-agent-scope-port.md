# fix/assistant-agent-scope → feat/overall-inspection 语义移植记录

- 日期：2026-11-01
- 来源分支：`fix/assistant-agent-scope` @ `db2a408`（3 个提交：`be52a43` / `ff67ebf` / `2f54268`）
- 目标分支：`feat/overall-inspection`（本地工作树，未提交）
- 方式：**不做 git merge**。按"行为意图重实现"逐条对照，落到 feat 当前架构上；
  已舍弃的旧文件（`NoteScopePicker` / `useNoteSuggestions` / `NoteSuggestionsInline` /
  `NoteSectionReader`）不复活。

## 1. 已移植

| fix 分支改动 | feat 上的落点 | 说明 |
|---|---|---|
| 人设取值与 `app.ai.personas` 单源化（修 422） | `app/schemas/assistant.py`、`app/schemas/conversations.py`、`tests/test_teacher_persona_contract.py` | `TeacherPersonaId` 改为 `Literal[tuple(PERSONA_IDS)]`；新增 `DEFAULT_TEACHER_PERSONA`；补"人设来自单源"测试 |
| `list_course_materials` 课件清单工具 | `app/ai/agent_read_tools.py`、`app/ai/agent_tools.py` | course/global 档注册；note 档不注册 |
| `read_material_page` 按页读 DocumentIR 原文 | 同上 | 含标题/公式/表格/图注；课程归属与页码越界校验；`fixed_material_id` 收窄 |
| Notebook 建议不支持按块部分采纳 | `features/assistant/DiffView.tsx`、`AgentCards.tsx` | `onToggle` 可选；`partial_supported=false` 时隐藏勾选框与"采纳所选项" |
| 新增测试 | `tests/test_agent_material_tools.py` | 7 例：注册范围、清单/读页、越界、跨课程拒绝、无效页码 |

## 2. 已被 feat 架构取代（无需移植）

| fix 分支改动 | feat 现状 |
|---|---|
| 锁定笔记档改用 `notebook_context` 方言 | 独立答疑页已改为 `NotebookScopePanel`：用 `/notebooks/{id}/conversations` 建**真正的 Notebook 会话**，请求自带 `notebook_context{notebook_id, revision}`；课程会话不再接受 note 档 |
| 选择器数据源换 notebooks API | `useNotebookIdentity` / `api.listNotebooks` 已是唯一数据源；旧 `noteApi.listNotes` 从 `api` 聚合退役 |
| 建议管线接入 notebook 端点 | `features/assistant/useNotebookEditSuggestions.ts` 已实现：课程级/单 Notebook 拉取、notebook review 端点、`expected_revision` 乐观锁、`onDocumentUpdated` 回推正文 |
| 悬浮坞阅读上下文去掉 `note_id` | feat 用 `useNotebookBridge` 传 `notebook_context`/选区块，旧 `reading_context.note_id` 已被后端 422 拒绝 |

## 3. 未移植（需要产品决策）

`allow_note_discovery` + `propose_notebook_edits`（发现模式下对课程内任意 Notebook 提交修改建议）：

- feat 的既有验收（P0-QA-06 / `tests/test_agent_notebook.py:71`）**明确断言该工具不存在**；
  路线图也写明"本轮不恢复 `propose_notebook_edits`，旧建议 API 保留待以后"。
- 因此本轮只搬了它的**只读**部分（列课件、读课件页），没有恢复写入口。
- 若之后决定开放，最小改动面是：`agent_tools.build_tool_specs` 增加
  `allow_note_discovery` 分支、`_propose_notebook_edits` 接受 `notebook_id`、
  `schemas/conversations.AgentMessageCreate` 加字段、`agent_loop`/`agent.py` 透传，
  并同步修改上面那条验收断言。

## 4. 验证

| 命令 | 结果 |
|---|---|
| `ruff check app tests` | 通过 |
| `pytest -q` | **517 passed / 4 skipped** |
| `npm test`（apps/web） | **81 files / 416 tests passed** |
| `tsc -b` | 通过 |
