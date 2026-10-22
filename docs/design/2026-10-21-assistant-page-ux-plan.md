# 答疑页交互体验改进计划

> 2026-10-21 · **v5**（三轮逐条核对后定稿；每条现状都核对到文件:行号，每条改动都落到具体文件与函数）
> 基线：`feat/agent-dialogue` 分支工作区现状（未提交改动）
> 覆盖范围：答疑页（`pages/AssistantPage.tsx`「答疑桌宠」）与共用同一条会话链路的悬浮坞（`features/assistant/AssistantDock.tsx`）
> 规范约定：
> - 文中「文件:行号」为核对时的**快照位置**，实现时以符号名为准；若代码已变，先更新本文再动手。
> - 「决策」= 已定、不再讨论；「后续项」= 明确不在本版，见 §7。
> - 每项功能的**后端改动文件数**在 §1、§2、§5 三处必须一致。
> - 路径简写：后端 `app/...` = `apps/backend/app/...`，`app/tests/...` = `apps/backend/tests/...`；前端 `src/...` = `apps/web/src/...`，`src/tests/...` = `apps/web/tests/...`。

### 实施记录

- **第一批（P1 + P2 + P5）已于 2026-10-21 落地**（纯前端，尚未提交）：
  - 改动文件：`features/conversation/useConversation.ts`（AbortController + `stopAgent` + 中断分支）、`features/assistant/AssistantComposer.tsx`（停止键 + Esc）、`features/assistant/AssistantThread.tsx`（已中断态 / 复制 / 重试 / chips / 用户时间）、`features/assistant/AssistantDock.tsx`（停止键 / 锁定三档）、`features/assistant/AssistantContextBar.tsx`（锁定预告）、`pages/AssistantPage.tsx`（接线）、`assistant-workspace.css`（新样式）。
  - 新增测试 11 个（`apps/web/tests/assistant-layout.test.tsx` 7 个、`apps/web/tests/dock-interaction.test.tsx` 4 个）。
  - 验证：`npx tsc -b` 通过；`npm run build` 通过；`npx vitest run` = 33 文件 / 181 用例全过；`npm run test:navigation` = 38 通过。
  - 行为取舍：中断后保留已收到的正文并标「已中断」，不写进历史（后端可能已落完整回答，属未实测项，见 P1 验收 3）；重试按 D1 会出现两条相同提问气泡。
  - 验收走查（自动）：P1-1 停止键与 Esc 生效（`assistant-layout.test.tsx` / `dock-interaction.test.tsx`）、P1-2 空闲时无停止入口、P1-4 「已中断」态不再显示「执行中」且保留正文；P2-1 复制落剪贴板并提示「已复制」、P2-2 失败卡重试重发原问题、P2-3 chips 只填草稿不发送、P2-4 用户气泡显示时间；P5b 三档禁用 + 课件仍可选 + 锁定提示、未提问时三档可选。
  - 验收走查（**待真机**）：P1-3「中断后刷新页面」的历史形态（取决于后端是否在断开后落库）、P2-2 重复气泡的观感、P5a 锁定预告的文案与位置。

---

## 0. 现状结论与决策记录

### 0.1 现状

答疑页的 agent 能力已与悬浮坞拉齐（流式 + 工具调用 + 建议卡 + 改动栏），但**交互层缺一批「对话产品标配」**，且前端把「检索范围」与「编辑目标」绑死。要补的两个能力，后端都**没有**真正就绪：

- **课件级收窄**：`material_id` 在 agent 链路空转。`api/v1/agent.py:128` 把它传给 `run_agent`，而 `ai/agent_loop.py:85` 只是签名接收，**函数体内零使用**（全文件仅 `:67` 的 `chunk.material_id` 是去重 key）。真正按课件检索的是经典链路 `ai/orchestrator.py:48-51`。因此悬浮坞的「课件」下拉目前**只是标签变化**，回答不会收窄。
- **非锁定范围改笔记**：`propose_note_edits` 的注册判据是 `editable_note_id`（`ai/agent_tools.py:94`），而 `api/v1/agent.py:126` 恒等于 `reading_note_id`（答疑页只在 note 档才传 `reading_context`）。叠加 `ai/prompts.py:152/159` 与 `219-223` 的「只能建议修改当前打开的笔记」，全局/课程档下 agent 连工具都没有。

### 0.2 版本演进

- **v2**：定「范围锁定机制保留」的专题结论；P4 定为「agent 自主定位并修改」；带上下文开新对话、范围消息级化下档。
- **v3**：修 5 处硬伤——P3 后端未就绪、P4 `note_id` 条件必填、多目标 diff 基准写坏风险、建议数据源缺口、提示词自我设限。
- **v4**：定三个决策（P2 重试、P4 坞接线、P3 收窄边界）+ 修口径不一致。
- **v5（本版）**：把 v4 的决策**落到具体文件与函数**，并补三处核对遗漏：
  1. **P4 的开关要打通一整条链路**，不是「`agent.py` 零改动」：`AgentMessageCreate` 不在 `schemas/api.py` 而在 `schemas/conversations.py:109`（`api.py:15-21` 只是 re-export）；`api/v1/agent.py:119-133` 的 `run_agent(...)` 是逐参数显式传参，新开关必须在此加一行；`run_agent` 再转给 `build_tool_specs`（`agent_loop.py:93`）与 `build_agent_messages`（`:94`）——**只改工具集不改提示词，坞会出现「提示词允许改任意笔记、工具却没有」的自相矛盾**。
  2. **P3 的「global+material → 422」在今天没有任何落点**：`api/v1/agent.py:70-72` 只校验资料是否属于当前课程，没有 scope 校验。v5 定在 schema 层校验（`schemas/conversations.py` 的 `model_validator`），FastAPI 自动 422。
  3. **「全部写入」今天必然 409（既有缺陷，P4 顺手修）**：`useNoteSuggestions.ts:113` 在采纳循环之后又调一次 `api.updateNote(note.id, content, note.revision_number)`，而循环里每次 `reviewSuggestion` 都会 `update_note_as_user` 递增 revision（`api/v1/notes.py:176-180` → `notes/service.py:19-26`）→ 必然冲突。用户看到「笔记刚在别处更新过」，但正文其实已写入，且 `setSuggestions([])` / `setAdopted` 被跳过 → 面板仍显示 pending、撤销不可用。

### 0.3 决策记录（本版不再讨论）

| # | 议题 | 结论 | 依据 |
|---|---|---|---|
| D1 | P2 重试去重 | **接受重复提问气泡**，后端重试能力列为后续项 | agent 端点对重复 key 直接 409（`api/v1/agent.py:61-68`）；新 key 会让后端再写一条 user 消息，`useConversation.ts:401-406` 刷新后两条都在 |
| D2 | P4 悬浮坞接线 | **坞保持单目标**；发现能力由 payload 开关 `allow_note_discovery` 控制，默认 `false`，只有答疑页传 `true` | 坞没有多目标宿主 UI（`AssistantDock.tsx:212-217` 的 hook 只认 `selectedNote`、`:367` 卡片正文也只传 `selectedNote`） |
| D3 | P3 收窄边界 | 收窄的是**课件检索与课件依据**；裁掉跨课/覆盖率工具；**笔记工具保留** | 笔记是用户内容，且 `read_note` / `list_course_notes` 是 P4 编辑与定位的必需（`agent_tools.py:79-87`） |
| D4 | P3 非法参数组合 | `material_id` **仅 course 档有效**；global/note 档携带 → 422（schema 校验） | `AgentMessageCreate.scope` 是 `Literal["note","course","global"]`（`schemas/conversations.py:114`） |
| D5 | P4 建议数据源 | `NoteSuggestion` 加 `note_title` property + 新增「按课程列待确认建议」端点 | `from_attributes` 不会自动生成字段（`schemas/proposals.py:37-47`），而 `NoteSuggestion` 已有 `note` 关系（`db/models.py:566`） |
| D6 | P4 面板语义 | 本版为「**本课程**待确认建议」；严格按会话归属需加列，列为后续项 | `NoteSuggestion` 无会话列（`db/models.py:553-566`） |

### 0.4 术语

- **范围（scope）**：会话级属性，三档 `global` / `course` / `note`，首轮定死（§4）。
- **收窄（material）**：消息级的「只看某一份课件」，不写会话 scope、不触发锁定。
- **发现（discovery）**：P4 里 agent 自主定位课程内任意笔记并对其提建议，由 `allow_note_discovery` 开关控制。
- **待确认建议**：后端 `note_suggestions` 表中 `status == "pending"` 的记录，挂在**目标笔记**上。

---

## 1. 优先级总表

| # | 功能 | 类型 | 后端改动 | 共享状态机风险 | 批次 |
|---|---|---|---|---|---|
| P1 | 中断正在进行的回答 | 流式控制 | 无 | 低（新增 `stopAgent`，两入口受益） | 一 |
| P2 | 回答卡二次操作（复制 / 重试 / 追问 chips / 用户消息时间） | 渲染增强 | 无（去重为后续项） | 低 | 一 |
| P5 | 范围锁定体验补丁（锁定预告 + 坞对齐） | 锁定机制配套 | 无 | 低 | 一 |
| P3 | 课件级收窄（整门课程 → 指定某份课件） | 能力补齐（坞当前只是标签） | **4 文件**（`agent_loop.py` / `agent_tools.py` / `prompts.py` / `schemas/conversations.py`） | 低 | 二 |
| P4 | agent 自主定位并修改笔记 | 编辑目标与范围解绑 | **8 文件**（`agent_tools.py` / `prompts.py` / `agent_loop.py` / `agent.py` / `schemas/conversations.py` / `schemas/proposals.py` / `db/models.py` / `api/v1/notes.py`） | **高**（共用 hook + 写坏数据风险 + 已知 409 缺陷） | 三 |
| P6 | 会话全文搜索（搜消息内容） | 检索 | **3 文件**（`api/v1/conversations.py` / `services/conversations.py` / `schemas/conversations.py`） | 低 | 四 |
| P7 | 锦上添花（桌宠反馈动画 / 草稿保持 / 反馈原因） | 打磨 | 无 | 低 | 有余力 |

> P1 / P2 / P5 纯前端；P1 的 signal 管道已由 `streamAgentMessage` 铺好（`api/agent.ts:39-49` 接收并转给 fetch，全前端无人使用）。
> **实际只有两个提问入口**：答疑页 + 悬浮坞。首页「问 AI」只是链接（`pages/HomePage.tsx:107`），不发起提问；旧 `ask(` 全前端零调用（grep 证实），勿按「三入口」规划回归。

---

## 2. 各项计划详述

### P1 · 中断正在进行的回答

**痛点**：agent 跑一轮实测 24s+，问错 / 等不及只能干等；composer 只有「正在翻资料…」禁用态，无任何中断入口。

**现状（代码事实）**
- `api/agent.ts:39-49`：`streamAgentMessage(..., signal?)` 已把 signal 传给 fetch，**管道已铺好**。
- `features/conversation/useConversation.ts` 的 `askAgent` 未创建 `AbortController`；composer 无停止按钮（全前端 grep `AbortController` 零命中）。

**目标交互**
- busy 时 composer 发送按钮变为「停止」（danger 样式），Esc 亦可中断。
- 中断后已收到的流式文本保留为一条带「已中断」标记的本地消息，不整段丢弃。
- 悬浮坞同步生效（共用同一份 conversation 状态，`stopAgent` 天然可用），坞内也放停止入口。

**实现要点（落点）**
> ✅ **已于 2026-10-21 实现（第一批）**，下方「落点」与行号已按实现后的代码更新。

1. `useConversation.ts`：`askAgent` 建 `abortRef`；catch 里区分 `AbortError`（`cause.name === 'AbortError'`）与真实错误；中断分支**不清空** `agentRun.streamingText`，改打 `aborted` 标记（`AgentRunState` 加 `aborted?: boolean`）。
2. **实时块门控**：`AssistantThread.tsx:285` 与 `AssistantDock.tsx:345` 的判据都是 `agentRun && !agentRun.final`——中断后 `agentRun` 仍在且没有 final，界面会**永远停在「Agent 执行中」**。两个入口都要加 `!agentRun.aborted`（或 busy）门控。
3. **中断消息不被重载冲掉**：`useConversation.ts:401-406` 每次 agent 成功后都 `listConversationMessages` 覆盖 history，catch 分支（`:408-430`）也会重载——本地「已中断」消息会被冲掉。**中断分支跳过这一次重载**，或把中断消息合并进历史。
4. 后端 user 消息在流开始前已 commit（`api/v1/agent.py:85-104`）——这点准确；但**「中断后历史上会留一条有问无答」不要先写死**：`api/v1/agent.py:143-169` 的持久化在生成器末尾，客户端断开后 `StreamingResponse` 是否取消同步生成器取决于运行时行为，可能继续把完整回答落库。验收以「中断后刷新页面」实测为准。
5. 竞态守门沿用现有 `historyRequestRef`，中断触发的历史重载不得覆盖其他会话的加载。

**涉及文件**：`features/conversation/useConversation.ts`、`features/assistant/AssistantComposer.tsx`（按钮态 + `onStop`）、`features/assistant/AssistantThread.tsx`（aborted 渲染 + 门控）、`features/assistant/AssistantDock.tsx`（停止入口 + 门控）、`pages/AssistantPage.tsx`（接线）、CSS 两文件（样式写进 `assistant-workspace.css`，见 §6）。

**验收**
1. 流式中点停止 → 按钮复位、实时块消失或标「已中断」、部分回答保留。
2. 停止后可直接再问。
3. 中断后刷新页面，历史状态与实测结论一致（结论写进 PR 描述，不预设）。
4. 切会话不串味。

---

### P2 · 回答卡二次操作

> ✅ **已于 2026-10-21 实现（第一批）**：复制 / 重试 / 追问 chips / 用户消息时间均已落地；
> 重试按 D1 接受重复气泡（PR 描述需写明这一限制）。

**痛点**：回答只能看不能复制；失败的回头路只有一句文案（「可以换个问法再试一次」）没有按钮；没有追问建议；用户消息不显示时间（回答卡显示）。

**目标交互**（挂在 `AnswerCard` / 用户气泡上）
- **复制**：回答卡 foot 加复制按钮，`navigator.clipboard` + 降级路径，成功后「已复制」反馈。
- **重试**：仅 failed 卡显示，取前一条 user 消息原文重发。**按 D1 接受重复提问气泡**。
- **追问 chips**：回答卡下方 2–3 个「展开讲讲 / 举个例子 / 和上一讲的区别」，点击**只填入草稿不自动发送**（复用 `useStarter` 模式）。
- **用户气泡显示时间**：复用 `AssistantThread.tsx` 内的 `messageTimeLabel`。

**重试方案的取舍（D1 展开）**
- 复用原 `askedAt`（同 `idempotency_key`）：**不可行**。agent 端点对重复 key 直接 409（`api/v1/agent.py:61-68`）；只有经典 `/messages` 端点才回放旧答案（`api/v1/conversations.py:181-194`），而答疑页/坞走的是 agent 端点；且对**失败的**回答，回放的还是失败结果。
- 新 key + 前端跳过本地 user 插入：**无效**。后端照样写入第二条 user 消息，`askAgent` 成功后 `useConversation.ts:401-406` 一刷新，两个气泡照样出现。
- 新 key + 抑制历史重载：**不可取**。UI 与库不一致，切走再切回或刷新页面重复气泡照样暴露，属于把问题藏起来。
- **采用**：新 key 正常重发，接受重复气泡（与用户手动把同一个问题再打一遍的行为一致，重试只是省了打字）。后续项见 §7-1。

**涉及文件**：`features/assistant/AssistantThread.tsx`（AnswerCard 内）、`pages/AssistantPage.tsx`（`onRetry` 接线，用当前 `agentOptions` 重发）、CSS 两文件。
> `useConversation.ts` 本项**无需改动**：重试就是一次普通的 `askAgent`，新 key 由调用方生成。

**验收**
1. 复制落剪贴板（失败时有降级提示）。
2. failed 卡重试后正常流式出结果；**提问气泡重复为已知限制**（PR 描述里写明）。
3. chips 点击只填草稿、不发送。

---

### P3 · 课件级收窄（界面补对齐 + 后端补能力）

**痛点**：课程资料多了以后，「针对整门课问」检索噪声高；用户想问「只针对第 3 讲」时无入口。

**现状（代码事实）**
- 前端传参链完整：答疑页 `agentOptions` 永远不传 materialId（`pages/AssistantPage.tsx:96-110`）；悬浮坞传（`AssistantDock.tsx:108-110`，且仅 course 档）。
- 端点校验存在：资料不属于当前课程 → 404（`api/v1/agent.py:70-72`）。
- **但 agent 链路根本不使用它**（见 §0.1）。模型也看不到这个 id，`search_course` 的 `material_id` 参数（`ai/agent_tools.py:62`）只能靠模型自己猜。
- 结论：**悬浮坞的「课件」下拉目前只是标签变化，回答不会收窄。**

**目标交互**
- 答疑页新增**独立的课件收窄控件**（composer 工具区 chip，点开列当前课程课件），**仅「整门课程」档显示**。
  - 不塞进现有二级菜单：那个是「锁定哪一门课程」（`AssistantContextBar.tsx:125-139`），混进去会把「切课程」和「收窄课件」搅在一起。
  - 仅 course 档显示的理由：global + material 语义矛盾（按 D4 → 422）；note 档已经是笔记级聚焦，再指定课件是冗余。
- 选中后作为**消息级** `material_id` 随发送：不写会话 scope、不触发锁定、不改范围 chip。

**收窄边界（D3 展开）**
- 收窄的是**课件检索与课件依据**：`search_course` 的检索与最终落库的来源只来自所选课件。
- 裁掉两个工具：`get_note_coverage`（覆盖率口径与「只看这讲」冲突）；`search_forest`（跨课程）——注意 `search_forest` 只在 global 档注册，而 global+material 已按 D4 被 422 拦掉，实际不会与 material 模式共存，裁剪只是兜底。
- **笔记工具保留**：`read_note` / `list_course_notes` 是 P4 编辑与定位的必需（`ai/agent_tools.py:79-87`），且笔记是用户自己的内容。回答中若用到笔记内容，须按笔记来源标注，**不计入「课件引用」**。
- 因此验收②的准确表述是：**课件依据（来源 chip 里的课程资料）只来自该课件**。

**后端改动（4 文件）**
1. `app/schemas/conversations.py`：`AgentMessageCreate`（`:109-120`）加 `model_validator(mode="after")`——`material_id` 仅在 `scope == "course"` 时允许；global/note 携带 → 抛错，FastAPI 自动返回 422。
2. `app/ai/agent_loop.py`：`run_agent` 已收 `material_id`（`:85`）；新增三件事——把 `material_id` 传给 `build_tool_specs`（`:93`）与 `execute_tool`（`:167`）；读取该课件标题（`db.get(Material, material_id)`）传给 `build_agent_messages`（`:94`），供提示词写明《X》这一讲。
3. `app/ai/agent_tools.py`：
   - `build_tool_specs(..., material_id=None)`（`:51-56`）：material 模式下不挂 `get_note_coverage`；`search_course` 的描述改成「已固定为用户所选课件」。
   - `execute_tool(..., material_id=None)`（`:276-303`）：命中 `search_course` 时，模型显式传了**别的** material_id → 直接返回确定性错误「用户已限定只关注当前课件」；没传则注入当前 material_id。
4. `app/ai/prompts.py`：`build_agent_messages(..., material_title=None)`（`:226-236`）；material 模式追加声明：「用户已限定只关注《X》这一讲；引用其他资料需说明理由」。

**方案选择**：方案 A（推荐）独立控件 chip；方案 B（可选后续）composer 支持 `@课件名` 语法，A 落地后再评估。

**涉及文件**
- 后端（4）：`app/ai/agent_loop.py`、`app/ai/agent_tools.py`、`app/ai/prompts.py`、`app/schemas/conversations.py`。
- 前端（3）：`pages/AssistantPage.tsx`（`agentOptions` 带 materialId + 选中态 + 仅 course 档显示）、`features/assistant/AssistantComposer.tsx`（收窄控件）、CSS。
- 测试：`apps/backend/tests/test_agent_tools.py`（注入 / 拒覆盖 / 工具裁剪）、`apps/backend/tests/test_agent_loop.py`（注入链路）、`apps/backend/tests/test_agent_api.py`（global/note + material → 422）。
> `api/agentStream.ts:57-65` 的 `AgentQuestionPayload` **已有** `material_id`，前端类型无需改动。

**验收**
1. 选课件后 payload 带正确 `material_id`。
2. **课件依据只来自该课件**（真机看来源 chip / 依据行，不只看参数）；若答案用到笔记内容，须按笔记来源标注。
3. 范围 chip 仍显示「整门课程」，不误锁、不写会话 scope。
4. 模型显式传别的 material_id 被拒（后端用例）。
5. global / note 档带 material_id → 422（后端用例）。
6. 切课程 / 切会话后收窄选择复位。
7. 悬浮坞回归：现状不变（下拉仍只是标签，直到 §7-3 落地）。

---

### P4 · agent 自主定位并修改笔记（风险最高项）

**痛点**：答疑页把「AI 能改哪篇笔记」绑在范围上——只有 note 档才带 `reading_context`（`pages/AssistantPage.tsx:96-110`），全局/课程档下 agent 连 `propose_note_edits` 工具都没有。用户锁着全局说「把《内聚与耦合》补全一下」→ agent 只能口头建议，改动栏永远空。

**目标交互（零新增 UI）**：用户锁全局照常对话；想改某篇笔记时**直接自然语言说**，agent 调用 `list_course_notes` / `search_forest` / `read_note` 自己定位，对定位到的笔记提交修改建议（pending）。用户不选任何东西，在建议卡上逐块审阅确认。

**发现能力的开关（D2）**
- `AgentMessageCreate.allow_note_discovery: bool = False`（新增字段）。
- **只有答疑页传 `true`**；悬浮坞不传（默认 false）→ 坞的行为与现在逐字节一致，回归面压到零。
- 开关同时是 kill switch：出问题关掉即回到现状。

**分两半看现状**

| 环节 | 现状 | 代码事实 |
|---|---|---|
| 查找 / 阅读 | ✅ 全局档已能 | `list_course_notes`（每条带 36 位 note_id，`ai/agent_read_tools.py:90-92`）/ `search_forest` / `read_note`（接受 note_id 参数）在 course/global 档均已注册（`agent_tools.py:79-93`） |
| 修改 | ❌ 被挡 | `agent_tools.py:170-177`：① `if not editable_note_id:` 直接拒；② `arguments.get("note_id") != editable_note_id` 拒——且**当前 schema 根本没有 note_id 参数**（`:99-119` 只有 rationale/edits），是「新增参数」不是「改必填」 |

**后端改动（8 文件）**
1. `app/schemas/conversations.py`：`AgentMessageCreate`（`:109-120`）加 `allow_note_discovery: bool = False`。
2. `app/api/v1/agent.py`：`run_agent(...)` 调用（`:119-133`）加 `allow_note_discovery=payload.allow_note_discovery`。
3. `app/ai/agent_loop.py`：`run_agent`（`:75-90`）收该参数，转给 `build_tool_specs`（`:93`）与 `build_agent_messages`（`:94`）。
4. `app/ai/agent_tools.py`：
   - `build_tool_specs(..., allow_note_discovery=False)`：注册条件改为 `editable_note or (allow_note_discovery and scope in ("course","global"))`（改 `:94` 的判据）；开关开且 scope ∈ {course, global} 时，`propose_note_edits` 的 `required` 含 `note_id`，描述要求「先定位再提交」；note 档描述维持「省略即锁定笔记」。
   - `_EXECUTOR_PARAMS["propose_note_edits"]`（`:271`）加 `scope`；`_propose_note_edits`（`:163-225`）改为：目标 = `arguments.note_id` 或 `editable_note_id`；note 档目标必须等于锁定笔记；course/global + 开关开却缺 `note_id` → 报错「先用 list_course_notes 定位」；仍走 `load_note(db, course_id, target)`（`agent_read_tools.py:29-35`）做课程护栏；两条确定性防线（`agent_tools.py:197-212`：对话文字混入、完全重复段落）保持不变。
   - `propose_knowledge_node` 仍挂在 `editable_note` 分支下（`:121-`），本项**不动**。
5. `app/ai/prompts.py`：`build_agent_messages(..., allow_note_discovery=False)`；**条件化改写，不做全局替换**——
   - 开关关（坞）或 scope=note：维持「只能建议修改当前打开的笔记」（`AGENT_SYSTEM:152/159`、`AGENT_SCOPE_LABELS:219-223` 原样）。
   - 开关开且 scope ∈ {course, global}：追加「允许定位课程内任意笔记：先用 list_course_notes / read_note 定位，再带 note_id 调用 propose_note_edits；禁止凭标题猜 ID」，范围标签改为「可建议修改定位到的笔记」。
   - **必须条件化**：直接全局改写会让坞出现「提示词允许改任意笔记、工具却没有」的自相矛盾（提示词与工具集不一致 = §4 第三根承重墙被破坏）。
6. `app/schemas/proposals.py`：`NoteSuggestionRead`（`:37-47`）加 `note_title: str | None = None`。
7. `app/db/models.py`：`NoteSuggestion`（`:553-566`）加 `note_title` property（`self.note.title if self.note else None`）——`from_attributes` 不会自动生成该字段，必须显式提供。
8. `app/api/v1/notes.py`：新增 `GET /api/v1/courses/{course_id}/note-suggestions?status=pending`（按课程列待确认建议，note_title 由 property 提供）。

**前端改动（8 文件）**
1. `src/api/agentStream.ts`：`AgentQuestionPayload`（`:57-65`）加 `allow_note_discovery?: boolean`。
2. `src/api/notes.ts`：加「按课程列待确认建议」封装。
3. `src/features/assistant/useNoteSuggestions.ts`：泛化为**按 note_id 的多目标**状态机（见下）。
4. `src/features/assistant/AgentCards.tsx`：`currentContent`（单一字符串）→ `currentContentByNoteId: Record<string, string>`；`:63` 的 `diffRows` 基准改为按 `suggestion.note_id` 取。
5. `src/features/assistant/ChangesPanel.tsx`：改动栏按笔记分组（`NoteChangeItem` 已有 `noteId` / `noteTitle` / `chapter` 字段）。
6. `src/features/assistant/NotePreviewDialog.tsx`：「当前正文」按预览项的目标笔记取。
7. `src/pages/AssistantPage.tsx`：传 `allow_note_discovery: true`；`scopeTargetId` 不再充当建议目标；extras 渲染改吃泛化后的 hook；预览 `current` 改为按目标笔记（现在传的是 `targetNote`，`:543`）。
8. `src/features/assistant/AssistantDock.tsx`：**不传开关**（行为不变）；但 `AgentCards` 的 prop 改成映射后，需传 `{ [selectedNote.id]: selectedNote.content_markdown }`（`:367`）。

**多目标状态机（可行性要点）**
- **目标集合** = 当前 final 事件里 `note_suggestion` 的 note_id ∪ 课程级 pending 端点返回的 note_id。
- **正文缓存**：工作区 `notes` 命中直接用；未命中用 `api.getNote(noteId)` 拉取并缓存（`src/api/notes.ts:6` 已有该接口）。
- **差异基准**：每条建议用 `noteById[suggestion.note_id].content_markdown` 作为 diff 基准（`AgentCards.tsx:63` 的参数化）。**这是数据安全红线**：多目标下若沿用单一正文，B 笔记的建议会拿 A 的正文当基准，采纳时拼出的整篇会写进 B。
- **采纳 review**：已按 `suggestion.note_id` 路由（`useNoteSuggestions.ts:51`），不变。
- **撤销 undo**：用 `noteById[suggestion.note_id].revision_number`（不是当前单篇的），回写采纳前正文。
- **全部写入 applyAll**：**按 note_id 分组**，每组以该篇当前正文为基准逐条累加（保持 `:107-111` 的累加语义），组间互不影响。
- **顺手修既有 409 缺陷**：`useNoteSuggestions.ts:113` 那次多余的 `api.updateNote` 必须删掉——循环里每次 `reviewSuggestion` 都会写笔记并递增 revision（`api/v1/notes.py:176-180` → `notes/service.py:19-26`），再用循环前的旧 revision 提交必然 409。改为以 `reviewSuggestion` 返回的 `NoteRead`（含新 revision）串联；`adopted` 记录**每篇笔记写入前**的正文，供撤销使用。

**面板语义（D6）**：课程级端点返回的是「本课程的待确认建议」，**不承诺只属于本会话**。本版把改动栏标题从「本次改动」改为「待确认改动（本课程）」并在卡上标注笔记标题；若要严格按会话归属，需给 `NoteSuggestion` 加 `conversation_id` 并迁移，列入 §7-2。

**歧义兜底**：「把内聚与耦合补全」但课程内有 2 篇标题相近笔记 → agent 可能选错。缓解：建议卡显示目标笔记标题（确认前可见）+ rationale 说明定位依据。手动指定笔记的入口仅在实测定位不准时再启用（不预设）。

**涉及文件汇总**：后端 8 个（见上）+ 前端 8 个（见上）+ 测试：`apps/backend/tests/test_agent_tools.py`（定位、拒越界、note 档回归）、`apps/backend/tests/test_agent_loop.py`（参数透传）、`apps/web/tests/note-suggestion.test.tsx`（多目标 diff 基准、审阅回归、全部写入不再 409）、`apps/web/tests/dock-interaction.test.tsx`（坞行为不变）。

**验收**
1. 全局范围说「把《某笔记》补全」→ 建议卡出现、标题正确 → 采纳 / 撤销闭环。
2. **目标为 B 篇时，diff 基准是 B 的正文**（构造 A、B 两篇不同笔记分别验证，确认不写坏 B）。
3. 刷新页面后建议仍在、标题正确（走课程级端点）。
4. 跨课程笔记不越界（agent 尝试改别的课 → 被 `load_note` 的课程护栏挡）。
5. 悬浮坞行为零变化（不传开关；采纳/忽略/撤销/全部写入全回归）。
6. 坞的「全部写入」不再出现 409（修掉既有缺陷）。
7. note 档 + 坞「锁定当前笔记」编辑链行为不变。
8. 不涉及笔记的回答行为零变化。

---

### P5 · 范围锁定体验补丁

> ✅ **已于 2026-10-21 实现（第一批）**：P5a 锁定预告在上下文条上；P5b 坞内三档禁用 + 课件列表保持可选 + 锁定提示。
> 「拆控件后整条禁」随第二批 P3 落地。

范围锁定机制本身保留（§4），只补两处体验，不动锁定逻辑。

**P5a 锁定预告**：首条消息发出前，范围 chip 旁轻提示「首条消息后范围将锁定」——把约束前置到用户做选择的那一刻，而不是事后 2.6s 闪现惩罚（`pages/AssistantPage.tsx:139-144` 的 `flashScopeLockHint`）。
文件：`features/assistant/AssistantContextBar.tsx`。

**P5b 悬浮坞锁定对齐（bug 修复）**：悬浮坞的范围下拉在 `hasMessages` 后**仍可改、标签照变、后端静默忽略**（`api/v1/agent.py:91` 的 `is_first_turn` 之后不写 scope；坞内无任何锁定处理，grep 证实）——用户改了范围、看到标签变了，收到的回答却还是旧范围。

**禁用范围要精确**：该下拉（`AssistantDock.tsx:286-299`）同时承担「范围三档」和「具体课件收窄」，而 `material_id` 是**消息级**参数（`api/v1/agent.py:70-72` 只校验不锁定）。

**批次约束**
- **第一批只有一种实现**：`hasMessages` 后只禁「锁定当前笔记 / 整门课程 / 全局可查」三档 + 显示锁定态（锁图标 + 同一句说明），**课件列表保持可选**（P3 落地前它还不生效，但禁用掉等于把入口关到第二批）。
- 「拆成独立控件后下拉整条禁」随第二批 P3 落地（拆控件本就是 P3 方案 A 的交付物）。
- `useConversation` 已暴露 `hasMessages`（`useConversation.ts:450`），零新增状态。

文件：`features/assistant/AssistantDock.tsx`。

---

### P6 · 会话全文搜索

**痛点**：`ConversationSearch` 只匹配会话标题（`features/assistant/ConversationList.tsx:283`），「上周问过的一个问题」搜不出来。

**目标交互**：Ctrl+K 面板分两级结果——「会话」（标题命中，现有）+「消息」（内容命中，显示命中句片段）；点消息命中 → 打开该会话并滚动定位、高亮该条消息。

**实现**
- 后端新端点 `GET /api/v1/courses/{course_id}/conversations/search?q=`：JOIN messages，`content LIKE`，返回会话 + 命中片段（上下文窗口截取）+ message id。
- 前端 `src/api/conversations.ts` 加 search；`ConversationList.tsx` 面板扩展两级。
- **定位时序**：`selectConversation`（`useConversation.ts:154-174`）先清空 history 再异步加载——高亮不能靠「切完再找」，需要 `pendingMessageId` 类状态：选中消息命中 → 记 id → 历史加载完 → 滚动定位 + flash 高亮。
- **搜索范围**：本版**只做课程内**。`ConversationSearch` 只拿当前课程的 conversations（`pages/AssistantPage.tsx:549-555`），端点也按 course_id；跨课程见 §7-4。

**涉及文件**：后端 3（`app/api/v1/conversations.py`、`app/services/conversations.py`、`app/schemas/conversations.py` 的 SearchResult）+ 前端 4（`src/api/conversations.ts`、`features/assistant/ConversationList.tsx`、`features/assistant/AssistantThread.tsx` 定位高亮、`features/conversation/useConversation.ts` 携带 pendingMessageId）+ CSS + 测试 `apps/backend/tests/test_conversation_manage.py`。

---

### P7 · 锦上添花（低优先，不计入批次）

| 项 | 说明 | 文件 |
|---|---|---|
| 桌宠回答完成反馈 | **不加新状态**：`TeacherStatus` 是四态且 `statusAssets` 是完整 `Record`（`components/TeacherCharacter.tsx:5,16-21`），新增状态必须配一张新立绘（目前只有 elf 一套）。复用 `explaining` + CSS 动画做完成反馈 | `components/TeacherCharacter.tsx`、`features/pet/PetAvatar.tsx` |
| 草稿保持 | 切课程路由重挂载丢 draft → 提升到 workspace 或 sessionStorage | `pages/AssistantPage.tsx`、`features/workspace/*` |
| 反馈原因捕获 | not_helpful 后弹小窗选原因（答非所问 / 引用不准 / 太啰嗦…），落 `feedback.comment`（`db/models.py:581`、`app/schemas/feedback.py:12` 已有该列）→ **无后端改动** | `features/assistant/AssistantThread.tsx`、`api/feedback.ts` |

---

## 3. 已下档项及理由

### 带上下文开新对话（v1 的 P5）
**下档理由**：头号场景「为了改某篇笔记不得不换范围」被 P4 吸收——全局内直接改，无需换范围。剩余场景「检索模式真想换」频率低，代价只是一次「＋新对话」。
**复活条件**：真实用户反馈上下文丢失痛感强。复活成本已知：后端 `createConversation` 加 `seed_from` 复制最近 N 条消息 + 前端右键菜单入口。

### 范围消息级化（设计 B）
讨论中评估过：会话保留分组锚点、检索/编辑目标全部消息级，可消掉锁定的一切代价。
**下档理由**：① 要推翻「范围是会话级属性」的既有设计（代码里满是刻意注释）；② 要加列迁移 + `is_first_turn` 全链路回归；③ 混合范围会话有心智负担。P4 已用「全局内挂编辑目标」拿到该方案约 80% 的收益，架构代价与收益不匹配。记录备查，不做。

---

## 4. 范围锁定：结论与理由

**结论：锁定机制保留不动，代价用 P4 + P5 补丁化解。**

### 为什么值得保留（三根承重墙）

1. **历史分组**：`features/conversation/conversationGroups.ts` 的 `buildHistory` 按 `conversation.scope / note_id` 把会话归进「全局可查 / 课程 → 整门课程 / 各篇笔记」。范围存在会话行上、首轮定死，分组才稳定——中途改范围会让会话在两组之间跳。
2. **自动命名**：`app/services/conversations.py:25-41` 的 `derive_conversation_title` 的范围前缀（「全局可查 · 」「《笔记名》 · 」）是首轮 scope 的快照。
3. **工具环境一致性**：`build_tool_specs(scope)`（`app/ai/agent_tools.py:51-56`）按范围装配工具（note 档只留聚焦工具、global 档才开 `search_forest`），首轮定范围 = 整段对话工具环境一致，agent 上下文不割裂。
   - **v5 补充**：P3 的课件收窄与 P4 的发现开关是**消息级例外**（收窄是用户显式指定的窄范围，发现开关默认关），不改变「范围是会话级属性」这一前提；但 P4 的开关若全局改写提示词而不同步改工具集，就会破坏这根墙——所以 P4 要求**提示词与工具集同步条件化**。

### 锁定的三个代价及化解

| 代价 | 化解 |
|---|---|
| 逃生门贵（锁定后只能开新对话丢上下文） | **P4**：编辑需求不再迫使换范围；剩余低频场景不值得专门做逃生门（§3） |
| 发现晚（锁定态只在尝试修改后 2.6s 闪现） | **P5a** 前置预告 |
| 悬浮坞内静默失效（改了范围后端忽略，标签照变） | **P5b** 禁用三档 + 锁定态对齐，**课件收窄保留**（消息级，锁定后仍有效） |

### 为什么不做消息级化
用户的关键洞察「全局是功能超集」成立——核对工具装配，note 档没有任何 global 档做不到的事（节选烘焙 + 编辑目标 = `reading_context`，本就是消息级参数），另两档相对 global 只提供限制（course：不许跨课；note：聚焦模式）。但推翻会话级 scope 的架构代价（§3）与 P4 已拿到的收益不匹配。

---

## 5. 需要修改的文件树（汇总）

```
Notebuddy/
├── docs/design/
│   └── 2026-10-21-assistant-page-ux-plan.md      # 本计划文档（v5）
│
├── apps/web/src/
│   ├── pages/
│   │   └── AssistantPage.tsx                     # P1 接线 / P2 onRetry / P3 收窄选中态 / P4 多目标接线+开关 / P6 pendingMessageId
│   ├── features/
│   │   ├── conversation/
│   │   │   └── useConversation.ts                # P1 AbortController + stopAgent + 中断分支 + 重载保护 / P6 选中携带 pendingMessageId
│   │   └── assistant/
│   │       ├── AssistantComposer.tsx             # P1 停止按钮 / P3 独立收窄控件（仅 course 档）
│   │       ├── AssistantThread.tsx               # P1 中断态渲染 + 门控 / P2 复制·重试·追问chips·用户消息时间 / P6 消息定位高亮
│   │       ├── AssistantContextBar.tsx           # P5a 锁定预告
│   │       ├── AssistantDock.tsx                 # P1 停止入口 + 门控 / P4 不传开关 + AgentCards 映射适配 / P5b 禁三档留课件
│   │       ├── useNoteSuggestions.ts             # P4 单目标→多目标状态机（按 note_id 分组；修 applyAll 的 409）
│   │       ├── AgentCards.tsx                    # P4 currentContentByNoteId（防写坏）
│   │       ├── ChangesPanel.tsx                  # P4 改动栏按笔记分组（标题改「待确认改动（本课程）」）
│   │       ├── NotePreviewDialog.tsx             # P4 预览「当前正文」按目标笔记取
│   │       ├── ConversationList.tsx              # P6 搜索面板两级结果
│   │       └── NoteScopePicker.tsx               # P4 不接入（agent 自主定位）；仅手动兜底预案再用
│   ├── api/
│   │   ├── agentStream.ts                        # P4 AgentQuestionPayload 加 allow_note_discovery（P3 无需改：已有 material_id）
│   │   ├── notes.ts                              # P4 按课程列 pending 建议封装
│   │   └── conversations.ts                      # P6 searchConversations
│   ├── components/
│   │   └── TeacherCharacter.tsx                  # P7（复用 explaining + CSS 动画，不加状态）
│   ├── course-assistant.css                      # 各批新增控件样式（停止按钮/chips/复制按钮…）
│   └── assistant-workspace.css                   # ⚠️ 后加载会覆盖前者：实测 89 个唯一选择器中 88 个与前者重名
│                                                   #    （按选择器解析口径可能有 ±1 差异）——新样式必须写进本文件或两处同步
│
├── apps/backend/app/
│   ├── ai/
│   │   ├── agent_tools.py                        # P3 注入/拒覆盖 material_id + material 模式裁剪工具 / P4 注册条件 + note_id 参数 + 提示文案
│   │   ├── agent_loop.py                         # P3 注入 material_id 到工具与提示词 / P4 透传 allow_note_discovery
│   │   └── prompts.py                            # P3 课件限定声明 / P4 条件化解除「只能改当前打开的笔记」
│   ├── api/v1/
│   │   ├── agent.py                              # P4 把 payload.allow_note_discovery 传给 run_agent（P3 无需改：422 走 schema 校验）
│   │   ├── conversations.py                      # P6 全文搜索端点
│   │   └── notes.py                              # P4 按课程列待确认建议端点
│   ├── services/
│   │   └── conversations.py                      # P6 搜索查询
│   ├── schemas/
│   │   ├── conversations.py                      # P3 material_id 仅 course 档（422 校验）/ P4 allow_note_discovery / P6 SearchResult
│   │   └── proposals.py                          # P4 NoteSuggestionRead 加 note_title
│   └── db/
│       └── models.py                             # P4 NoteSuggestion.note_title property
│
└── 测试（随各批同步补）
    ├── apps/web/tests/
    │   ├── assistant-layout.test.tsx             # P1 中断 / P2 复制重试 / P3 materialId
    │   ├── dock-interaction.test.tsx             # P1/P4/P5b 共用回归
    │   └── note-suggestion.test.tsx              # P4 多目标 diff 基准 / 审阅 / applyAll 不再 409
    ├── apps/web/tests/*.test.ts                  # 纯逻辑测试走 npm run test:navigation（node --test）
    └── apps/backend/tests/
        ├── test_agent_tools.py                   # P3 注入/拒覆盖/裁剪 / P4 定位、拒越界、note 档回归
        ├── test_agent_loop.py                    # P3-P4 参数透传链路
        ├── test_agent_api.py                     # P3 material_id 非法组合 → 422
        └── test_conversation_manage.py           # P6 搜索
```

**后端文件数核对**：P3 = 4（`agent_loop` / `agent_tools` / `prompts` / `schemas.conversations`）；P4 = 8（`agent_tools` / `prompts` / `agent_loop` / `api.v1.agent` / `schemas.conversations` / `schemas.proposals` / `db.models` / `api.v1.notes`）；P6 = 3。P3 与 P4 都会改 `schemas/conversations.py`，按批次顺序落地即可。

---

## 6. 实施顺序与回归纪律

**批次划分**
1. **第一批（P1 + P2 + P5）**：纯前端、互不依赖，一个分支三个提交。P5b 只做「禁三档 + 保留课件列表」。
2. **第二批（P3）**：后端 4 文件 + 前端收窄控件（仅 course 档）；与 P5b 的「整条禁」变体在此批收尾。
3. **第三批（P4）**：后端 8 文件 + 前端多目标状态机——**全表风险最高**（写坏笔记的数据事故风险 + 共用 hook + 开关语义），独立分支，悬浮坞必须一起回归（验证开关不传时行为不变）。
4. **第四批（P6）**：含后端新端点，独立分支。

**每批完成定义（DoD）**
- `npm run build` 通过（`tsc -b && vite build`）。
- 本批相关测试通过（前端 `npx vitest run <相关文件>`；纯逻辑 `.test.ts` 走 `npm run test:navigation`；后端 `uv run pytest <相关文件> -q`）。
- 本文该批的验收条目逐条走查，结论写进 PR 描述（**不预设结论**，尤其是中断后的落库行为）。
- 改动到的行号引用在本文同步更新。

**回归纪律（本项目历史教训，逐条遵守）**
- 改完必须跑 `npm run build`——`tsc --noEmit` 通过 ≠ 构建通过。
- 改答疑页样式前先查 `assistant-workspace.css` 有没有同名规则（它后加载，几乎全部重名，会静默覆盖）；新样式统一写进 `assistant-workspace.css`。
- 纯逻辑 `.test.ts` 不被默认 `vitest run` 收录（`vitest.config.ts` 的 include 只有 `tests/**/*.test.tsx`），必须走 `npm run test:navigation`。
- **测试基线是 flaky，不当硬指标**：全量并行运行下，森林 / 知识树相关文件（`chapter-tree-return` / `forest-page` / `home-relation-location` / `tree-directory-growth`）会间歇失败。本日多次实测全量结果在 **0–4 个失败文件**之间波动，同一文件组合有时全过（8/8）有时部分失败（11/14），属并行时序污染。**判定标准：失败文件是否落在上述四组之内；缩小范围复跑可过即非本批引入**；若失败落在其他文件，按真实回归处理。
- 真机验证不要改共享数据库的状态做测试（`note_suggestions` 的 pending/accepted 会被其他会话看到）；要改先打印原状态、验完逐条还原。
- P4 涉及 `useNoteSuggestions`，回归范围 = 答疑页 + 悬浮坞两条入口的采纳 / 忽略 / 撤销 / 全部写入；**P4 上线前必须构造 A / B 两篇不同笔记验证 diff 基准不串**。

---

## 7. 后续项（本版明确不做）

1. **后端「重试」能力**（消除 P2 的重复气泡）：agent 端点支持按消息 id 重试 + 失败 assistant 消息的替换 / 作废语义。做完重试按钮即可无重复。
2. **建议按会话归属**（P4 面板语义回到「本会话」）：`NoteSuggestion` 加 `conversation_id` + 迁移 + 工具链路透传会话 id。
3. **悬浮坞的课件收窄真正生效**：坞的下拉目前只是标签；P3 的后端能力落地后，坞需决定是复用还是拆控件。
4. **跨课程会话搜索**（P6）：入口与端点都要去掉 course 维度。
5. **更严格的课件收窄**：把 `read_note` / `list_course_notes` 也限制到所选课件的笔记（需处理 `Note.material_id` 可空的情况，`db/models.py:355`）。
6. **composer 的 `@课件名` 语法**（P3 方案 B）。
7. **范围消息级化**（§3 已下档）。
