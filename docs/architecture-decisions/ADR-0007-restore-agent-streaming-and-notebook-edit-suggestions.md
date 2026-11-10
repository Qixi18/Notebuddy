# ADR-0007：恢复答疑过程可见性与 Notebook 编辑建议工具

- 状态：**Proposed**（待技术把关者与协作者审核；不能视为已批准架构）
- 日期：2026-11-06
- 审查基线：`feat/agent-edit` @ `46d9ea9`
- 关联决策：修订 [ADR-0002](ADR-0002-verified-notebook-assistant-and-file-budget.md) S2 批（P0-QA-02「统一核验后发布」）中"过程不可见"的部分；**完整保留其核验留档契约**

## 背景

2026-11-01 提交 `1aed783`（P0-QA-02，ADR-0002 S2 批）为修复两个 P0 级缺陷，关闭了答疑过程可见性：

- **P0-QA-01**：模型生成的证据编号仅凭格式合法即可冒充支撑依据（已由 `app/ai/qa_evidence.py` 带类型证据标识与 AnswerGate 白名单修复）。
- **P0-QA-02**：答案边生成边实时下发，证据核对在完成后进行，用户会先读到未核验正文。

当时的修复把 SSE 改为：吞掉 `thinking` 事件（只统计 `thinking_ms`/`thinking_chars`）、缓冲全部正文 delta 到 `verify_answer` 门禁通过后按 180 字符/片回放（`app/services/agent_execution.py:370-384,478-482`）、中断不落草稿、思维链不落库。契约同步写入 `docs/backend-data-contract.md` 与 `test_agent_reasoning_visibility.py`。

付出的产品代价：回答期间用户只能看状态转圈，正文一次性出现（假流式），思考过程不可见、历史不可回看；Agent 无法提出 Notebook 编辑建议（`propose_notebook_edits` 在 `build_tool_specs`/`_EXECUTORS` 中被守卫注释标注为"intentionally guarded until the A2 verifier exists"，`app/ai/agent_tools.py:64-71` 及建议产生端未注册）。

## 决策

经技术把关者复核，按"保留安全核心、放宽过程可见性"修订契约：

1. **真流式恢复**：`run_agent` 产生的 `delta` 事件在门禁前实时下发；前端草稿标注"生成中·未核验"。`verify_answer` 门禁**原样保留**，仍唯一决定：最终答案落库内容、`mode`/核验徽标、失败时整段丢弃并落 failed 消息。核验失败时前端清空草稿并显示错误。
2. **思考链恢复**：`thinking` 事件实时外发并重新落库——写入 `ConversationMessage.process_json` 的 `thinking` 字段（截断 20000 字符），历史消息可展开回看（`MessageProcess` 渲染已存在）；`thinking_ms`/`thinking_chars` 统计保留。
3. **不变量（与 P0-QA-02 一致，不得回退）**：
   - 落库的 `ConversationMessage.content` 只能是 `verify_answer` 输出的核验后正文；
   - 核验失败/中断不落未核验草稿（`GeneratorExit` 语义不变）；
   - 部分主张缺证据仍打 `partially_verified` 并把口径写进 `verification.notice`，不污染正文；
   - Notebook 专用核验管线（`run_notebook_answer`）本轮不变。
4. **启用编辑建议产生端**：注册 `propose_notebook_edits` 工具（spec + `_EXECUTORS` + `_EXECUTOR_PARAMS`），仅当 `editable_notebook_id` 存在时暴露；Agent 修改正文的唯一路径仍是创建待审 `NotebookEditSuggestion`，经现有 review 端点以 `write_document` CAS（`origin="ai_suggestion"`）应用，**禁止任何静默覆盖**。既有门禁（可编辑范围校验、ops 数量 1.._MAX_EDITS、空正文/超长/对话性文字/重复段落四道内容门禁）全部保留。

## 兼容与回滚

- 旧消息 `process_json` 无 `thinking` 字段，前端按缺省渲染，向后兼容；新消息多出的字段对旧客户端无影响（SSE 为自由 JSON dict）。
- 前端在 `notice`（agent 失败回退标准问答）与 `error` 时清空当前流式草稿，避免显示被替换的内容。
- 回滚：本批为单切片提交，`git revert` 即可恢复 P0-QA-02 原契约。
- 对其他协作者的影响：本 ADR 修订 P0-QA-02 决策，PR 中需注明并通知原作者复核；如协作者对取舍有异议，在合并前于 PR/ADR 评审中解决。

## 挂起项（后续切片）

- 悬浮坞在 Notebook 页的会话范围：改用 `scope="note"`（与答疑页共用 `run_agent` 工具链路，编辑建议可用；答疑页 Notebook 严格核验面板保持只读）或扩展 notebook 专用管线——待拍板后实施 Notebook 页端到端编辑流。
- `NotebookScopePanel` 独立会话实例与旧 `scope="notebook"` 会话的呈现，随上一项处理。

## 验证要求

- 后端：`test_agent_reasoning_visibility.py` 按新契约重写（SSE 含 thinking 原文与门禁前 delta、process_json 含 thinking、落库内容仍为核验后正文、失败/中断不落草稿）；`test_agent_notebook.py` 的"不能创建编辑建议"用例改为正向用例（创建 pending 行、final 携带建议卡、越界与内容门禁仍拒绝）；`test_agent_execution_service.py`、`test_course_verified_qa.py`、`test_notebook_edit_suggestion_review.py` 回归。
- Web：vitest 覆盖思考链实时渲染、未核验草稿标注与清空、`note_suggestion` 卡渲染与 accept 流程。
- 浏览器人工验收与真实模型/材料验收单独记录，不以自动测试替代；真实付费模型联调须单独授权。
