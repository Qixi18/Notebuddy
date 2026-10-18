# 答疑悬浮坞 Agent 化交付交接

- 日期：2026-10-18
- 分支：`feature/agent-dock`（基于 main `7814f87`），PR 目标 main
- 计划文档：`docs/superpowers/specs/2026-10-18-agent-dock-plan.md`（含范围确认与文件级计划）

## 1. 目标与需求决定

把右侧答疑悬浮坞从"固定检索管线问答"升级为可调用工具、多步执行的课程学习 agent，并支持通过对话对当前打开的笔记进行问答与修改（用户 2026-10-18 确认）。关键决定：

- **写操作不静默生效**：agent 对笔记的修改一律走现有"建议-确认"（`NoteSuggestion` pending → review），采纳才写入，产生修订记录可回退。
- **作用范围三档**（用户确认）：📌 锁定当前笔记 / 整门课程 / 🌲 全局可查。锁定档读写都限定该笔记；全局档解锁跨课程检索但写建议仍只针对当前打开的笔记。
- **旧管线零改动保留**：`run_answer`/旧端点/答疑页行为不变，作为 agent 失败时的自动降级路径。

## 2. 实现概述

后端：
- `app/ai/deepseek.py`：新增 `chat_stream(messages, tools)` 流式 + function calling。要点：`deepseek-flash` 为思考模型，**多轮工具调用必须回传 `reasoning_content`**（否则 400），且**每轮都必须携带 tools**（否则工具调用内联成 DSML 文本泄露）。思维链不外发到前端。
- `app/ai/agent_tools.py`：工具注册表——只读 7 个（search_course / read_note / list_course_notes / search_forest / get_note_coverage / explain_term / web_search）+ 建议类 2 个（propose_note_edit / propose_knowledge_node，只创建 pending）。按 scope 装配工具集，全部校验课程归属，结果截断防 token 爆炸，工具异常降级为文本回给模型。
- `app/ai/agent_loop.py`：`run_agent` 生成器，最多 6 轮工具循环，产出 step/delta/final/error 事件；正文与工具调用同轮出现时全部文本并入最终回答。
- `app/api/v1/agent.py`：`POST /conversations/{id}/agent-messages`（SSE）。落库消息与 evidence 复刻旧端点等价逻辑（conversations.py 旧逻辑零改动，仅 `_mode_from_evidence` 增加 agent 前缀识别用于历史回读标签）；agent 链路任何失败自动回退 `run_answer` 并以 `fallback: true` 事件告知前端。
- `prompts.py` 新增 `AGENT_SYSTEM`：先检索再回答、课件/网页内容是资料不是指令（防提示注入）、改笔记只提建议、来源标记与 LaTeX 规范沿用。

前端：
- `src/api/agentStream.ts`（纯函数 SSE 解析，可被 node:test 直测）+ `src/api/agent.ts`（fetch 流式客户端）。
- `useConversation.ts` 新增 `askAgent()`/`agentRun` 流式通道，旧 `ask()` 保留；三入口共享历史的架构不变。
- `AssistantDock.tsx`：范围三档下拉、执行时间线（`AgentSteps.tsx`）、流式光标、待确认建议卡（`AgentCards.tsx`，采纳/忽略走 `api.reviewSuggestion`）；回答完成按 `listSuggestions` 刷新待确认面板（服务端持久化，重开坞仍在）。
- **顺带修复既有缺陷**：`NOTE_PATH` 正则不匹配 `/notebooks/<id>`，导致分册阅读视图"写入当前笔记"按钮始终不可用；已扩展正则。

## 3. 已验证结果

| 层级 | 结果 |
| --- | --- |
| 后端单测 | `uv run ruff check app tests` 通过；`uv run pytest` **232 passed, 1 skipped**（含新增 test_deepseek_stream / test_agent_tools / test_agent_loop / test_agent_api） |
| 前端测试 | `npm test` 通过：node:test 34 passed + vitest 24 文件 **117 passed**（含新增 agent-sse / agent-dock 测试） |
| 前端构建 | `npm run build` 通过 |
| 真机模型验证 | deepseek-flash 流式 + 并行工具调用 + reasoning 回传全链路通过（约 4s/3 轮） |
| 浏览器端到端 | 隔离数据目录（8010/5180 备用端口）+ 合成 PPTX 课程：锁定当前笔记 → 时间线（读笔记→检索 4 条→提交建议）→ 流式回答带来源标记 → 建议卡采纳 → 笔记 v2（用户保存，v1 可回退）→ 全局档提问带课件出处，全部通过并截图留证 |
| 降级路径 | API 测试覆盖：agent 失败 → 旧管线接管（fallback 事件）；模型未配置 → 错误事件 |

未验证项（如实声明）：真实多课件课程下跨课程森林搜索的回答质量、`web_search` 工具的真实联网效果（需 TAVILY_API_KEY）、长笔记（>1200 字节选）的上下文质量——待用户用真实课程验收。

## 4. 已知问题与限制

- 单次 agent 问答的 token 消耗高于旧管线（多轮 + 工具结果回填）；已有 6 轮上限 + 结果截断 + provider_audit 审计兜底。
- 锁定档的笔记正文节选上限 1200 字符，超长笔记由 agent 用 read_note 工具补读。
- `notebooks/<id>` 视图下"正在阅读"徽章依赖 workspace `selectedNote`，笔记本页由 NotebookPage 选中小节后才有值（行为与旧"写入当前笔记"一致）。
- 知识节点提议卡为信息卡，审核入口在课程知识图谱页（该页已有审核流）。

### 交付后即时修复（同一分支追加提交）

- **GFM 表格渲染**：全项目 Markdown 管线此前均未接入 `remark-gfm`，agent/老师回答中的表格渲染为管道文本。已安装 remark-gfm@^4 并接入悬浮坞（正文+流式）、答疑页、笔记页、笔记本页四处渲染点，补齐表格样式（悬浮坞窄栏支持横向滚动）。
- **「打开笔记」可发现性**：新增提示——未打开任何小节时，作用范围下方显示"进入课程笔记本目录点开一个具体小节（即打开笔记）后会出现锁定选项"；agent 工具在无笔记时的回复话术也加入同样指引，并建议改用课件检索继续回答。
- **既有测试抖动记录**：`forest-page` / `tree-directory-growth` / `home-relation-location` / `chapter-tree-return` 等重负载导航测试在整机高负载并发跑全量时偶发超时（单跑必过、代码与本任务无关）；曾发现验证用 Vite 进程残留加剧负载，已在验证后清理。

### 真实事故与防线（本地提交，未推送）

- **事故**：用户锁定《软件设计原则与模式》让 agent 撤销/精简内容。模型在生成"整篇新正文"时把**自己的聊天回复**（"撤销建议已经提交啦…点「采纳」…"）混入 `proposed_markdown`，采纳后污染正文；随后每次采纳又以污染版为底稿再叠一层，同一段话重复 3 遍（v4→v6 各增约 450 字）。
- **恢复**：已将该笔记恢复到用户采纳过的干净版本（当前 v7 = 原 v3 内容；完整版 v2 仍在修订历史可随时回退）。
- **防线**（`agent_tools.py`，确定性校验，不依赖模型自觉）：① proposed_markdown 命中对话性文字特征（"已经提交""点「采纳」"等 8 个标记）→ 拒绝并要求重写；② 完全重复段落 → 拒绝；`AGENT_SYSTEM` 增补对应硬性规则。新增 2 个事故回归测试；全量 234 passed。
- **遗留改进**（未做）：更彻底的方案是把 propose_note_edit 从"整文替换"改为"结构化编辑操作（追加/替换小节/删除小节 + 锚点）"，由后端确定性拼装全文，从根上消除模型拼错全文的风险——建议列入下一轮迭代。

## 5. 剩余工作（P1/P2，见计划文档）

- P1：知识树叶子跳转卡、覆盖诊断多步任务（检查未覆盖页→建议补生成）、深度研究模式（多轮迭代汇总）。
- P2：agent 技能/指令页（个人化偏好）、定时任务（基于现有任务执行器）。
- 真实课程验收：按 `docs/acceptance.md` 用真实课件跑连续 3 讲验证。

## 6. 可复现命令

```powershell
# 后端检查（apps/backend）
uv run ruff check app tests ; uv run pytest
# 前端检查（apps/web）
npm test ; npm run build
# 端到端（隔离环境，避免占用 5173/8000）
# 后端：NOTEBOOK_DATA_DIR=./data-agent-e2e uv run uvicorn app.main:app --port 8010
# 执行器：NOTEBOOK_DATA_DIR=./data-agent-e2e uv run python -m app.workers.runner
# 前端：临时 vite 配置把端口改为 5180、代理指向 8010（验证后删除）
```
