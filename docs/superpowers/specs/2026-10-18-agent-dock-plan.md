# 答疑悬浮坞 Agent 化实施计划

- 日期：2026-10-18
- 状态：**P0 已实现并通过本地验证**（详见文末「实际交付记录」）；当前进入本地迭代完善阶段，**新改动只提交本地、暂不推送**。
- 需求来源：用户要求把右侧 AI 答疑悬浮坞从"单轮检索问答"升级为真正能干活的 agent（对标 Notion Agent 能力），并支持通过 agent 对话对当前打开的笔记进行编辑与问答（2026-10-18 用户确认）。
- 范围：本文档为 P0 实施计划；P1（知识树叶跳转卡、覆盖诊断多步任务、深度研究模式）、P2（技能库、定时任务）为后续迭代，不在本次。

## 1. 目标与范围

把悬浮坞从"固定检索管线问答"升级为"工具调用 agent"：

1. agent 具备工具调用与多步执行能力（对标 Notion Agent 的核心机制：LLM 工具循环 + 工作区上下文 + 可见执行过程）。
2. agent 可感知并操作当前打开的笔记：问答基于笔记内容；修改笔记走"建议-确认"卡片，用户点采纳才写入（硬约束：AI 修改不静默生效，保护用户正文）。
3. 旧问答管线原样保留，作为降级路径；答疑页、首页入口行为不变。

## 2. 现状核查（2026-10-18 代码事实）

| 事实 | 位置 |
| --- | --- |
| 悬浮坞组件（318 行）：全局挤压式抽屉 + 拖拽调宽 + 持久化 | `apps/web/src/components/AssistantDock.tsx`、`apps/web/src/features/assistant/dockLayout.ts`、挂载于 `AppLayout.tsx:227-239` |
| 三个入口（首页/答疑页/悬浮坞）共用会话状态；`ask()` 一次性 await，**无流式** | `apps/web/src/features/conversation/useConversation.ts:159-205` |
| 请求只传课程/课件/页码/学习目标；**当前笔记正文、知识树状态不进 prompt** | `apps/web/src/api/conversations.ts:11-15` |
| 后端固定管线：检索→条件联网(Tavily)→DeepSeek JSON 生成/降级摘录；**全仓库无 function calling** | `apps/backend/app/ai/orchestrator.py:35-273` |
| DeepSeek 客户端仅 `complete`/`complete_json`，`stream: False` | `apps/backend/app/ai/deepseek.py:28-94` |
| 答疑端点同步返回；evidence 落库与 sources 还原逻辑可复用 | `apps/backend/app/api/v1/conversations.py:184-296,32-95` |
| **建议-确认基础设施已存在**：笔记建议 pending→review→confirm（`create_note_suggestion` / review 端点）、知识提案 `create_knowledge_proposal`/`apply_proposal` | `apps/backend/app/knowledge/proposals.py:21,89,169`、`apps/backend/app/api/v1/notes.py:134-176` |
| 前端建议接口已有：`listSuggestions`/`reviewSuggestion` | `apps/web/src/api/notes.ts:14-17` |
| 当前笔记状态在 workspace 中已有（`selectedNote`），悬浮坞可直接取用 | `apps/web/src/features/workspace/useWorkspaceState.ts:47` |
| 检索服务签名（agent 工具复用） | `apps/backend/app/retrieval/service.py:85` `retrieve(db, *, course_id, question, material_id, page_number, limit)` |
| 人设与输出规范 | `apps/backend/app/ai/personas.py`、`apps/backend/app/ai/prompts.py:87-101`（ANSWER_SYSTEM） |
| 路由注册方式：模块列表循环 include | `apps/backend/app/api/v1/routes.py:21` |
| 前端测试目录为 `apps/web/tests/`（vitest），后端为 `apps/backend/tests/`（pytest） | `apps/web/tests/dock-interaction.test.tsx` 等 |

## 3. 用户体验层面的功能点（改完后悬浮坞的 6 个新能力）

1. **流式回答**：逐字出现 + 打字光标，不再白屏等待。
2. **干活过程可见**：回答上方显示 agent 工作时间线（正在检索第 3 讲课件 → 正在阅读你的笔记 → 正在跨课程查找 → 正在生成回答），完成后折叠为摘要。
3. **作用范围三档（用户显式选择，2026-10-18 追加确认）**：检测到正在阅读笔记时，悬浮坞「作用范围」下拉顶部出现「📌 锁定当前笔记」选项；三档为——
   - **锁定当前笔记**：prompt 自动携带该笔记正文与当前小节；`read_note`/`propose_note_edit` 只作用于这一篇；课件检索仍可用（保证回答有出处，锁定的是操作对象而非视野）；
   - **整门课程**：现有默认行为；
   - **全局可查**：解锁跨课程工具（`search_forest` 森林搜索）；写建议仍只针对当前打开的笔记，agent 认为其他笔记需修改时只能文字提示，由用户打开后再提建议。
   - 未锁定笔记时当前笔记仅作为可选参考上下文（开关保留）。
4. **对话式操作笔记**：如"把这一节整理成要点写进笔记"→ agent 产出**修改建议卡**（摘要+预览）→ 用户点「采纳」（走现有 review 接口，产生修订记录可回退）或「忽略」。
5. **更聪明的多步检索**：agent 自主决定调用哪些工具（课程内检索、读笔记、跨课程森林搜索、覆盖查询、术语解释、联网），复杂问题不再依赖单遍检索。
6. **失败不打扰**：agent 链路出错（无 key、接口异常、超轮次）自动回退现有问答管线，行为与现状一致。

## 4. 架构对比

- **改前**：`POST /conversations/{id}/messages` → `run_answer()` 固定管线，同步返回整段 JSON。
- **改后**：新增 agent 通道：SSE 流式端点 → agent 循环（模型自主多轮调用工具）→ 工具层复用现有服务 → 写操作落"建议-确认"。旧管线保留为降级路径与旧入口通道。

不改框架 agent 无从谈起：单次同步请求无法承载"多步执行 + 过程可见 + 流式输出"。

## 5. 文件变更规划（文件树）

```
apps/backend/
  app/ai/
    deepseek.py          [修改] 新增 chat_stream(messages, tools)（旧方法不动）
    prompts.py           [修改] 追加 AGENT_SYSTEM + build_agent_messages
    agent_tools.py       [新建] 工具注册表：7 只读 + 2 建议类工具
    agent_loop.py        [新建] agent 循环，产出事件流（step/delta/final/error）
  app/api/v1/
    agent.py             [新建] SSE 端点 POST /conversations/{id}/agent-messages
    routes.py            [修改] 注册新路由（1 行）
  app/schemas/
    conversations.py     [修改] 追加 ReadingContext + AgentMessageCreate（含 scope 三档）
  tests/
    test_agent_tools.py  [新建]
    test_agent_loop.py   [新建]
    test_agent_api.py    [新建]

apps/web/src/
  api/
    agent.ts             [新建] SSE 客户端（fetch + ReadableStream，解析函数独立可测）
  features/
    conversation/
      useConversation.ts [修改] 新增 askAgent 流式通道（旧 ask 保留）
    assistant/
      AgentSteps.tsx     [新建] 工作步骤时间线组件
      ActionCards.tsx    [新建] 建议卡片组件（采纳/忽略）
  components/
    AssistantDock.tsx    [修改] 流式、时间线、范围三档选择器（锁定当前笔记/课程/全局）、建议卡（拖拽/收合框架不动）
  types.ts               [修改] agent 事件/建议类型
  features/assistant/answerMeta.ts [修改] 增加 agent 模式标签
  styles.css             [修改] 时间线/卡片/光标样式
apps/web/tests/
  agent-sse.test.ts      [新建] SSE 解析器测试
  agent-dock.test.tsx    [新建] 时间线/建议卡渲染测试
```

**完全不动的文件**（复用而非修改）：`orchestrator.py`（旧管线=降级路径）、`retrieval/`、`web_search/`、`parsers/`、`workers/`、`knowledge/proposals.py`、`notes/service.py`、`personas.py`、数据库模型与迁移（**无表结构变更**：建议/提案表已存在，agent 回答存现有 `conversation_messages`）、`AppLayout.tsx`、`dockLayout.ts`、desktop/、scripts/。

## 6. 逐文件说明

### 后端

**1. `app/ai/deepseek.py`（修改）**
- 逻辑框架：不变，仍是 DeepSeek HTTP 薄封装，只新增方法。
- 为什么/好处：现有方法不支持 `tools` 与流式；独立新增保证旧管线零风险。
- 改成什么样：`chat_stream(messages, tools)` 生成器——httpx `stream=True` 逐块解析，产出 `delta`（文本增量）/ `tool_calls`（工具调用及参数）/ `usage`（接现有 provider_audit 审计）。
- 效果：agent 循环有了"会流式输出、会调工具"的模型底座。

**2. `app/ai/agent_tools.py`（新建）**
- 内容：① `TOOL_SPECS`（9 个工具的 JSON Schema）；② `execute_tool(db, course_id, name, args)`。
- 只读工具 7 个：`search_course`（包 retrieve+rerank）、`read_note`（校验课程归属）、`list_course_notes`、`search_forest`（跨课程）、`get_coverage`、`explain_term`、`web_search`（复用 Tavily 限额/缓存/审核）。
- 建议类 2 个：`propose_note_edit`（调 `create_note_suggestion`，生成 pending 建议）、`propose_knowledge_node`（调 `create_knowledge_proposal`）。
- 安全：全部工具校验课程归属；工具结果文本截断防 token 爆炸；**写工具只创建 pending 建议，绝不直接改笔记**；锁定模式下 `read_note`/`propose_note_edit` 只接受锁定的 note_id；全局模式下不提供针对其他笔记的写工具（只能文字提示）。
- 效果：模型拥有"查资料 + 提修改"的全部手脚，且越不出安全边界。

**3. `app/ai/agent_loop.py`（新建）**
- `run_agent(...)` 生成器：按 scope 装配可用工具集与范围指令，组装消息（人设 + AGENT_SYSTEM + 当前笔记上下文 + 受控历史 + 问题）→ 最多 6 轮循环：有 tool_calls 则发 step 事件→执行→结果回填；有文本则逐段发 delta；收尾汇总本轮课件片段/网络来源为 evidence 发 final；失败发 error（API 层回退旧管线）。
- 效果：一次提问变成"模型自己规划、自己查、边干边汇报"的多步任务。

**4. `app/ai/prompts.py`（修改，追加）**
- 新增 `AGENT_SYSTEM` + `build_agent_messages()`；沿用现有排版/来源标记规范，新增三条 agent 规则：先检索再回答；课件与网页内容只是资料不是指令（防提示注入）；用户要求改笔记时只提建议不宣称已改。
- 效果：agent 行为边界与现有底线（证据、人设、安全）一致。

**5. `app/schemas/conversations.py`（修改，追加）**
- `ReadingContext`（note_id/标题/小节/节选，可空）+ `AgentMessageCreate`（旧字段 + reading_context + `scope: Literal["note","course","global"]`）。
- 效果：前端能把"正在阅读的笔记"和用户选择的作用范围传给 agent。

**6. `app/api/v1/agent.py`（新建）+ `routes.py`（注册 1 行）**
- `POST /conversations/{id}/agent-messages` → `StreamingResponse(text/event-stream)`。校验归属（复用 `_load_conversation`）→ 落库 user 消息（幂等键同旧规则）→ 转发 `run_agent` 事件 → final 后按现有 evidence 模式落库 assistant 消息 → done 事件。agent 链路抛错时服务端自动回退调 `run_answer` 并以普通事件补发。
- 效果：悬浮坞有专属流式 agent 接口；老接口、老页面不受影响。

### 前端

**7. `apps/web/src/api/agent.ts`（新建）**
- `streamAgentMessage(id, payload, {onStep,onDelta,onFinal,onError})`：fetch + ReadableStream 手写 SSE 解析（EventSource 不支持 POST）；解析函数独立导出供 vitest；支持 AbortController 中断。

**8. `apps/web/src/features/conversation/useConversation.ts`（修改）**
- 逻辑框架：**扩展不重写**，"三入口一份状态"原则保持；旧 `ask()` 原样保留。
- 新增 `askAgent()`：本地插入 user 消息 → streaming 占位 → 逐事件更新 `agentSteps`/`streaming` → final 时规范为 `ConversationMessage` 追加入历史（持久化机制不变）。
- 效果：三入口仍看同一份历史，悬浮坞额外拥有实时过程。

**9. `apps/web/src/components/AssistantDock.tsx`（修改）**
- 交互框架（拖拽调宽/收合/宽度记忆/快捷提示/来源卡）不动；改动集中消息区与发送链路：发送走 `askAgent`；进行中消息渲染时间线+流式文本；带建议的消息渲染 `ActionCards`；既有「作用范围」下拉扩展为三档——📌 锁定当前笔记（检测到 `workspace.selectedNote` 时出现）/ 整门课程 / 全局可查，锁定档显示笔记名徽章并注入笔记上下文（数据源现有，无需新共享状态）；「写入当前笔记」（全文追加）保留，与建议卡（定点修改）互补。

**10. `AgentSteps.tsx` / `ActionCards.tsx`（新建）**
- 时间线（工具名+状态，完成折叠）；建议卡（摘要/预览/「采纳」调 `reviewSuggestion`/「忽略」置 rejected）。

**11. `types.ts`、`answerMeta.ts`、`styles.css`（修改，追加）**：新类型、`agent` 模式标签、样式。

## 7. 实施步骤

| 步骤 | 内容 | 验证 |
| --- | --- | --- |
| 0 | 已完成：本地 main 快进至 `7814f87`（含悬浮坞改进版）。开工时 `git checkout -b feature/agent-dock`（基于 main）；本计划文件随任务分支首次提交入库 | `git log` 确认基点 |
| 1 | `deepseek.py` 加 `chat_stream` | 单测 + **真实 key 做 tools+流式 smoke test**；若 DeepSeek 不支持，降级为"JSON 动作协议"（模型输出指令 JSON 代替原生 function calling，计划仍成立） |
| 2 | `agent_tools.py` | `test_agent_tools.py`：课程隔离、user_locked 保护、建议只进 pending |
| 3 | `agent_loop.py` + prompts + schemas + `agent.py` + 路由 | `test_agent_loop.py`（假客户端多轮）、`test_agent_api.py`（事件序列/幂等/回退）；`uv run ruff check app tests` + `uv run pytest` 全绿 |
| 4 | `agent.ts` + `askAgent` | `apps/web/tests/agent-sse.test.ts`；`npm test` |
| 5 | Dock UI + 两组件 + 样式 + answerMeta | `npm test` + `npm run build` |
| 6 | 手动端到端（`./scripts/dev.ps1` + worker + 合成课程） | 清单：流式/步骤/范围三档切换（锁定当前笔记/整门课程/全局可查）/"改笔记→采纳→笔记更新且修订可回退"/跨课程搜索/删 key 自动回退/答疑页不受影响 |
| 7 | 交接文档（`docs/handoffs/2026-10-18-agent-dock.md`）+ 提交 + PR（目标 main） | 核对提交身份（mawenzhe33），仅含本任务文件 |

## 8. 风险与约束

- **成本**：多轮调用比单次费 token；靠"最多 6 轮 + 工具结果截断 + provider_audit 用量审计"控制。
- **安全**：课件/网页内容视为数据而非指令（提示注入防护）；写操作只走建议-确认；`user_locked` 与乐观锁由现有 service 保证；API 仅监听 127.0.0.1。
- **降级**：agent 链路任何失败回退旧管线；模型不可用时仍有 local-retrieval-fallback。
- **验收边界**：交付时明确区分"代码已实现 / 本地合成验证通过 / 真实课件与真实 AI 质量验收"——后者需用户用真实资料确认，不得写成已完成。

## 9. Git 状态记录（2026-10-18 制定计划时）

- 会话开始时分支为 `feature/sidebar-flat-nav`（6bf9d32 悬浮坞改进版）；后经合并（PR #6 途径）**该提交已在 origin/main 中**。
- 本地 main 已快进至 `7814f87`（= origin/main，含悬浮坞改进版与知识树首页 PR #7），工作区干净。
- 因此 agent 任务分支基点 = **main（7814f87）**，命名 `feature/agent-dock`，PR 目标 main。
- 本计划文件在开工前保持未跟踪状态（不直接在 main 上提交）；随 `feature/agent-dock` 首次提交入库。

## 10. 实际交付记录（2026-10-18，P0 完成后回填）

### 10.1 实际变更文件树

与第 5 节计划的差异：新增 `agentStream.ts`（SSE 解析纯函数，便于 node:test 直测）、
`conversations.py`/`api.py` 有小幅必要改动（agent 模式标签识别、schema 兼容导出）、
后端测试拆为 4 个文件、前端渲染层额外接入 `remark-gfm`（修复全项目表格不解析的既有缺陷）。

```
apps/backend/
  app/ai/
    deepseek.py          [修改] 新增 chat_stream：流式 + function calling；
                                  思考模型 reasoning_content 回传、并行工具调用、每轮必须带 tools
    prompts.py           [修改] 新增 AGENT_SYSTEM（工具规则/来源规范/注入防护）+ build_agent_messages
    agent_loop.py        [新建] run_agent 事件循环：≤6 轮工具调用，产出 step/delta/final/error，
                                  思维链不外发、工具失败降级为文本
    agent_tools.py       [新建] 工具注册表：search_course / read_note / list_course_notes /
                                  search_forest / get_note_coverage / explain_term / web_search（只读 7 个）
                                  + propose_note_edit / propose_knowledge_node（只建 pending）；
                                  按 scope 装配，全部校验课程归属，结果截断
  app/api/v1/
    agent.py             [新建] POST /conversations/{id}/agent-messages（SSE）；
                                  消息与 evidence 等价复刻旧落库；agent 失败自动回退 run_answer
    routes.py            [修改] 注册 agent 路由
    conversations.py     [修改] 仅 _mode_from_evidence 增加 agent 前缀识别（历史回读标签），旧端点行为不变
  app/schemas/
    conversations.py     [修改] ReadingContext + AgentMessageCreate（scope: note|course|global）
    api.py               [修改] AgentMessageCreate / ReadingContext 兼容导出
  tests/
    test_deepseek_stream.py  [新建] 5 用例：流式事件/分片聚合/reasoning 回传/无 key/HTTP 错误映射
    test_agent_tools.py      [新建] 9 用例：范围装配/课程隔离/锁定限制/建议 pending/错误降级/森林搜索
    test_agent_loop.py       [新建] 5 用例：事件序列/建议收集/无 key/轮次上限/工具失败降级
    test_agent_api.py        [新建] 4 用例：SSE 流与落库/降级回退/幂等 409/范围与归属校验

apps/web/
  src/
    api/agentStream.ts   [新建] SSE 帧解析纯函数 + agent 事件/载荷类型（零运行时依赖，node:test 直测）
    api/agent.ts         [新建] streamAgentMessage：fetch 流式客户端（EventSource 不支持 POST）
    components/AssistantDock.tsx
                         [修改] 发送走 askAgent；范围三档选择器（锁定当前笔记/整门课程/全局可查）；
                                  执行时间线 + 流式光标实时块；待确认建议卡与知识提议卡；
                                  「如何打开笔记」提示；NOTE_PATH 扩展匹配 /notebooks/<id>（修复既有缺陷）；
                                  Markdown 渲染接入 remark-gfm
    features/conversation/useConversation.ts
                         [修改] 新增 askAgent()/agentRun 流式通道与 AgentRunState；旧 ask() 保留
    features/assistant/AgentSteps.tsx   [新建] 执行时间线（running→done 折叠）
    features/assistant/AgentCards.tsx   [新建] 笔记修改建议卡（采纳/忽略）+ 知识提议信息卡
    features/assistant/answerMeta.ts    [修改] agent 模式标签（完整 + 短版）
    pages/AssistantPage.tsx             [修改] remark-gfm
    pages/NotesPage.tsx                 [修改] remark-gfm
    pages/NotebookPage.tsx              [修改] remark-gfm
    styles.css           [修改] 时间线/光标/建议卡/表格样式（窄栏横向滚动）+ 打开笔记提示样式
  tests/
    agent-sse.test.ts    [新建] 3 用例：帧拆分/五类事件/坏帧容错（node:test）
    agent-dock.test.tsx  [新建] 6 用例：范围三档调用/时间线与流式/知识提议卡与建议采纳/GFM 表格/无笔记提示
    dock-interaction.test.tsx [修改] mock 扩展（askAgent/agentRun/listSuggestions）
  package.json           [修改] 新增 remark-gfm@^4.0.1
```

### 10.2 交付状态与提交

| 提交 | 内容 | 状态 |
| --- | --- | --- |
| `5b0449e` | P0 主体（后端 agent 层 + SSE 端点 + 前端 dock 改造 + 计划/交接文档） | 已推送 origin/feature/agent-dock |
| `e355a36` | 追加修复：GFM 表格渲染、「打开笔记」引导（UI 提示 + agent 话术） | 已推送 origin/feature/agent-dock |
| 此后改动 | **按用户要求只提交本地、暂不推送**，待功能完善后一并处理 | 本地 |

验证状态：后端 ruff + pytest 232 passed；前端 node:test 34 + vitest 全绿（个别森林/首页重负载导航测试在整机高负载下偶发超时，单跑必过，与本任务无关）；npm run build 通过；真机 deepseek-flash 循环与浏览器端到端（锁定笔记→时间线→流式→建议卡→采纳→笔记 v2 可回退→全局档）全部通过。

### 10.3 待完善（本地迭代中，等待具体需求）

- P1 候选：知识树叶子跳转卡、覆盖诊断多步任务、深度研究模式；P2 候选：技能/指令页、定时任务。
- 体验类：表格在极窄栏下的阅读优化、回答中笔记内链跳转、agent 过程的耗时可展示化。

## 11. 笔记 Agent 二轮调研与后续功能规划（2026-10-18）

### 11.1 业界参照（调研结论）

- **Obsidian Copilot V4**：把 agent 化工具引入本地笔记库——检查笔记、搜索整理、创建命令、写入，本地优先、可插自有模型。与我们"本地单用户 + 自有 key"的定位最接近。
- **Notion 3.0 / Custom Agents**：agent 批量建库改页、按触发条件自动运行；**社区报告其 agent 更新页面时会破坏排版**——印证"模型整文重写不可靠、需确定性编辑"的判断，与我们已加的写入防线方向一致。
- **编辑 UX 行业收敛**（Cursor/Kiro/JetBrains/写作工具）：词级/块级 inline diff、逐块 Accept/Reject、先审后应用、建议锚定到稳定位置。
- **Mem 等 AI-first 知识库**：自动组织与连接、自然语言问答。

### 11.2 后续可实现功能（按梯队）

**第一梯队（下一轮建议，直击写入安全与体验）**
1. **结构化编辑操作**：`propose_note_edit` 从"模型输出整篇新文"改为"操作指令"（追加 / 在某小节后插入 / 替换某小节 / 删除某小节 + 锚点），后端确定性拼装全文——从根上消除整文拼错风险。
2. **逐块 diff 审查**：建议卡展示块级 diff，支持逐块采纳/拒绝（Cursor 式），替代"全文预览 + 一揽子采纳"。
3. **采纳后一键撤销**：卡片在采纳后保留"撤销本次 AI 改动"按钮（回退到采纳前修订）。
4. **回答内小节跳转**：回答引用笔记内容时带小节锚点，点击直达笔记本对应小节。

**第二梯队（价值明确，规模中等）**
5. **跨笔记语义检索**：为笔记正文建向量索引（复用 EMBEDDING_* 配置与检索框架），"我哪篇笔记讲过 X"不再依赖标题关键词。
6. **笔记间关系提议**：agent 复用知识提案通道提议小节间关系（deepen/repeat），审核后进入知识图谱。
7. **Agent 指令页（个人化）**：偏好页（默认精简风格、常用动作），注入 AGENT_SYSTEM。

**第三梯队（需用户先做范围决策）**
8. **定时/触发任务**：上传新课件后自动起草小结、定期汇总新增笔记——复用现有 worker；属于新增范围。
9. **跨会话记忆**：从对话学习偏好（"我喜欢表格总结"）并可管理删除。
10. **闪卡/测验生成**（作为建议走确认流）——超出首期必做范围，需确认后立项。
11. **本地 MCP 服务**：把笔记库的搜索/读取/建议工具以 MCP 暴露给外部 agent，本机监听。

### 11.3 约束提醒

所有写路径继续遵守"建议-确认 + 修订可回退 + 来源规范"；8/10/11 属于超出首期承诺的新范围，需用户明确立项后再排期。

## 12. 第一梯队实施设计（2026-10-18 确认动工：结构化编辑 + 逐块 diff + 一键撤销）

### 12.1 机制设计

1. **结构化编辑操作**：agent 不再输出"整篇新文"，改调 `propose_note_edits({ rationale, edits[] })`，四种操作——
   `append`（文末追加）、`insert_after_heading`（在某标题小节末尾插入）、`replace_section`（替换某小节正文，保留标题行）、`remove_section`（删除小节含标题及其子块）；`anchor` 为标题文本。
   后端把操作**依次**应用到当前正文工作副本：锚点解析（精确标题匹配 → 唯一子串匹配 → 失败返回候选标题清单）；任一操作失败整单拒绝并回报原因。
   产出最终全文存入现有 `NoteSuggestion.proposed_markdown`——**零数据库迁移**，既有 review 流程兼容；对话标记/重复段落守卫改为对最终全文生效。
2. **逐块 diff 审查**：前端 `noteDiff.ts` 行级 diff（LCS，纯函数、node:test 直测）把「当前正文 vs 建议全文」分成变更块；卡片渲染红删绿增，**每块独立勾选**（默认全选）；「采纳所选项 (n/m)」把选中块拼装成 `final_markdown` 提交。
3. **部分采纳后端支持**：`ProposalReview` 增加可选 `final_markdown`；confirm 时若提供则以其为准（与 proposed 不同则 impact 追加"部分采纳"）。**不提供时行为与旧版完全一致**（旧建议照常整文替换）。
4. **一键撤销**：采纳成功后卡片保留「撤销本次 AI 改动」——前端用采纳前正文 + 当前修订号 PATCH 回去；期间笔记被改过则 409 提示刷新。

### 12.2 文件清单

```
后端：
  app/ai/agent_tools.py        [修改] propose_note_edits 工具（section 解析/锚点/操作执行/守卫），移除旧整文重写工具
  app/ai/prompts.py            [修改] AGENT_SYSTEM 笔记修改规则改为操作指令说明
  app/schemas/proposals.py     [修改] ProposalReview + final_markdown（可选）
  app/api/v1/notes.py          [修改] review confirm 支持 final_markdown（部分采纳标注）
  tests/test_agent_tools.py    [修改] 操作执行/锚点歧义/守卫/整流程用例
  tests/test_agent_api.py      [修改] review final_markdown 部分采纳用例
前端：
  src/features/assistant/noteDiff.ts   [新建] 行级 diff + hunk 分组（纯函数）
  src/features/assistant/AgentCards.tsx [修改] diff 红绿视图、逐块勾选、采纳所选项、采纳后撤销
  src/api/notes.ts                     [修改] reviewSuggestion 支持最终正文
  src/components/AssistantDock.tsx     [修改] 传入当前正文、撤销回调接线
  src/styles.css                       [修改] diff 红绿行/勾选样式
  tests/note-diff.test.ts              [新建] diff 纯函数用例（node:test）
  tests/agent-dock.test.tsx            [修改] 逐块采纳与撤销交互用例
文档：
  docs/superpowers/specs/2026-10-18-agent-dock-plan.md [修改] 本节
  docs/handoffs/2026-10-18-agent-dock.md               [修改] 实施记录回填
```
