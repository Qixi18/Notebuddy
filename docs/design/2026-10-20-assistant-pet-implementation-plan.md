# 答疑桌宠 · 改造实施计划（对齐 v3 视觉稿）

- 日期：2026-10-20（rev.2，对应界面规范 rev.7）
- 分支：`feat/agent-dialogue`
- 视觉基准：`docs/design/assistant-pet-ui-v3.html` / `.png`
- 设计规范：`docs/design/2026-10-20-assistant-pet-ui-spec.md`
- 范围：**只改答疑桌宠页**，不动其他页面、不动后端 RAG 与提示词

---

## 一、当前代码与目标界面的差距

| 目标（v3 rev.7） | 当前代码 | 差距 |
|---|---|---|
| 三栏：240 历史 + 阅读列 + 280 改动栏 | 两栏：300 左栏 + 自适应正文 | 页面结构要重写 |
| 回答是一张卡，依据收在卡底一行 chips | 依据折叠在消息底部，来源卡点击跳走 | 新建回答卡与来源行 |
| 句末角标 `[1]` | 正文里的 `[课程资料：…]` 标记未消费 | 新建 citations 解析 |
| 历史按「课程 → 整门课程/笔记」分组 | 一个 `<select>` 下拉，无分组 | 需要分组组件 + 数据字段 |
| 右侧「本次改动」列表（+/−、预览、全部写入） | 无 | 新组件，且依赖 agent 数据 |
| 桌宠站在纸面圆盘上，可拖出浮层 | 固定在左栏卡片里 | 重做桌宠区 + 页内拖拽 |
| 正文 14.5px，无渐变，深绿只做强调 | 13px，深绿卡 + 渐变 | 新样式层 `.ws-*` |
| 上下文条两个 chip + 新对话 | 藏在 `<details>` 里的 4 个下拉 | 新上下文条 |

**结论**：页面是重写，不是改样式。但**数据层大部分够用**，只有两处要后端配合（见第四节）。

---

## 二、改动范围

### 2.1 前端：修改

| 文件 | 改什么 | 逻辑是否变 |
|---|---|---|
| `apps/web/src/pages/AssistantPage.tsx` | 重写为三栏编排，约 150 行 | 是（结构） |
| `apps/web/src/course-assistant.css` | 追加 `.ws-*` 视觉层；旧 `.pet-*` 暂留 | 否（新增） |
| `apps/web/src/features/assistant/AssistantMessageContent.tsx` | 不改；新组件 `CitationText` 复用其 Markdown 管线 | 否 |

### 2.2 前端：新建

| 文件 | 内容 | 依赖 |
|---|---|---|
| `features/assistant/citations.ts` | 解析 `[课程资料：讲次 \| 第 N 页]`、`[网络来源 N]`、`[通用解释]`、`[模型推断]` → 角标 + 清洗正文 | 无 |
| `features/assistant/CitationText.tsx` | Markdown + 自定义 `a` 渲染角标 | citations |
| `features/assistant/AssistantContextBar.tsx` | 范围 / 目标 chips + 新对话 | 无 |
| `features/assistant/AssistantThread.tsx` | 消息流：气泡、回答卡、动作条 | CitationText |
| `features/assistant/SourcesRow.tsx` | 卡底「依据 n 段」chips + 查看原文 | citations |
| `features/assistant/AssistantComposer.tsx` | 输入卡（Enter 发送、停止） | 无 |
| `features/assistant/ConversationList.tsx` | 课程 / 笔记两级分组，可折叠 | conversationGroups |
| `features/assistant/ChangesPanel.tsx` | 本次改动列表、展开预览、收起、全部写入 | B2 接口 |
| `features/assistant/TermDialog.tsx` | 术语查询弹层（保留现有能力） | `api.explainTerm` |
| `features/conversation/conversationGroups.ts` | 把会话按 course / note / global 分组（纯函数） | 会话字段 |
| `features/pet/petLayout.ts` | 尺寸、clamp、比例换算 | 无 |
| `features/pet/petPhysics.ts` | 速度采样、摩擦、边界（纯函数） | 无 |
| `features/pet/usePetDrag.ts` | pointer + rAF + 落点判定 | 上两个 |
| `components/pet/PetStage.tsx` | 立绘 + 浅绿圆盘 + 状态 | TeacherCharacter |

### 2.3 前端：不动

`AppLayout.tsx`、`AssistantDock.tsx`、`useConversation.ts`、`api/*`、`App.tsx`、`AgentSteps.tsx`、`AgentCards.tsx`、`dockLayout.ts`。

> 这意味着：本阶段桌宠浮层**只在答疑页生效**；跨页悬浮是下一阶段（要改 `AppLayout`）。

### 2.4 后端：可选但建议同期（两个小任务）

| 任务 | 内容 | 影响 |
|---|---|---|
| **B1** 会话归属 | `conversations` 增加 `scope`、`note_id`、`note_title`；**并把 `ConversationCreate.default_scope` 的枚举从 `course\|material\|page` 统一成 `course\|global\|note`**（现在它和 agent 的 `note\|course\|global` 是两套词）；创建时写入；列表返回 | 历史分组的笔记/全局两层才能亮 |
| **B2** 改动聚合 | `note_suggestions` **增加 `conversation_id`**（现在只有 `note_id`，无法按会话聚合）；写入建议时带上；新增 `GET /conversations/{id}/changes` | 右侧改动栏才有真实数据 |

不做 B1/B2 也能上线：历史只到「课程 → 整门课程」一层，改动栏保持空态收起。

**三处已知不一致（必须在本计划里处理）**

1. **范围词表有两套**：`ConversationCreate.default_scope` 的正则是 `^(course|material|page)$`，而 agent 传的是 `note|course|global`。历史分组如果直接用 `default_scope`，笔记/全局永远对不上。B1 要定一套：`course`（整门课）/ `global`（跨课程）/ `note`（锁定笔记），旧的 `material`、`page` 一律映射为 `course`。
2. **建议没有会话外键**：`note_suggestions` 只有 `note_id`，`source_ids_json` 是证据引用，不是会话。B2 必须加 `conversation_id` 才能回答"这次会话改了哪几篇"。**存量建议没有这个字段，改动栏只能显示新产生的建议**——这点要在文案里说清，不能假装能回溯历史。
3. **会话列表只加载当前课程**：`useConversation(courseId)` 内部调 `api.listConversations(courseId)`，只拿到一门课。左栏要显示多门课的历史，需要：① 前端按 `courses` 并行拉取（课程少时够用），或 ② 后端加 `GET /conversations`（跨课程）。P3 之前必须先定这条，否则左栏只有当前课程。

---

## 三、关键实现细节

### 3.1 角标：消费已有标记，不改后端

后端提示词已要求模型输出 `[课程资料：讲次 | 第 N 页]`，`extract_claims` 也按段落解析，所以前端直接消费：

```ts
// citations.ts
const COURSE = /\[课程资料：([^\]|]+?)\s*\|\s*第\s*(\d+)\s*页[^\]]*\]/g
const WEB    = /\[网络来源\s+(\d+)[^\]]*\]/g
const GENERAL = '[通用解释]'
const INFERENCE = '[模型推断]'

export function parseAnswer(content: string, sources: AssistantSource[]) {
  // 课程标记：按 lecture_title + page_number 精确匹配 sources → 编号 = 下标 + 1
  // 网络标记：按 web 来源出现顺序匹配；匹配不到不编号
  // 通用/推断：渲染为不带编号的「通」「推」小标
  // 返回 { text: 清洗后的正文, refs: CiteRef[] }
}
```

匹配不到的标记**降级为纯文本**，不猜编号——宁可少标，不能标错。

### 3.2 回答卡与来源行

回答卡把头像、名字、时间放进卡头，正文、来源行、动作条依次排列：

```
┌ 莉艾尔 14:02 ───────────────────────────┐
│ 先说结论：…                        [1] │
│ · …                                [2] │
│ ▣ 红黑树的四条性质（callout）           │
│ ─────────────────────────────────────  │
│ 依据 3 段  [1 第3讲·p.18] [2 …] [3 …] 查看原文→ │
│ 有帮助 需改进                 复制回答 │
└────────────────────────────────────────┘
```

点角标：对应 chip 高亮（`aria-current`），不滚动页面。

### 3.3 历史分组：先课程，后笔记

```ts
// conversationGroups.ts
type Group = { key: string; kind: 'global' | 'course' | 'note'; title: string; meta: string; items: Conversation[] }
```

- 无 B1 字段时：所有会话 `kind='course'`，`title=course.name`，只有「整门课程」子组。
- 有 B1 后：按 `scope` 分出 global / course / note，note 组挂在所属课程下。
- 排序：课程按最后活动倒序，组内同理；时间只作行尾信息。

### 3.4 改动栏：先空态，后接数据

- 组件始终渲染；无数据时 `collapsed`，竖排显示「改动 0」。
- 有数据：行 = 笔记名 + 章节 + `+n −n`；点行展开预览；底部「全部写入笔记」。
- 「全部写入」= 对每条 pending 建议调用 `reviewSuggestion(note_id, id, 'confirm')`，逐条失败要能回滚提示。

### 3.5 桌宠：页内浮层

- 默认站在左栏顶部（浅绿圆盘 + 绿色名字），不是卡片。
- 拖出后 `position: fixed`，页面内任意位置；6px 阈值区分点击；松手吸附；位置写 `localStorage`。
- 双击、`Home`、左栏锚点「召回」三条归位路径。
- 不改 `AppLayout`，所以离开答疑页就看不见——这是本阶段的已知限制。

---

## 四、分步计划

原则：每一步可单独合并、可回滚；P0–P3 纯前端，P4–P5 依赖后端。

### P0 · 视觉骨架（1 天）

| 项 | 内容 |
|---|---|
| 改 | `AssistantPage.tsx`（三栏骨架，先接静态占位）、`course-assistant.css`（`.ws-*` 令牌与布局） |
| 验收 | 1440 下三栏比例与稿一致；1440/1024/390 不塌；无渐变 |
| 回滚 | 只回滚页面与样式，不牵数据 |

### P1 · 对话主线与角标（1.5 天）

| 项 | 内容 |
|---|---|
| 新建 | `citations.ts`、`CitationText.tsx`、`AssistantThread.tsx`、`AssistantComposer.tsx` |
| 验收 | 提问、回答、反馈不回归；角标可点；正文不露 `[课程资料：` 原文 |
| 测试 | `citations.test.ts`（精确匹配 / 未命中降级 / 去重编号） |

### P2 · 依据行（0.5 天）

| 项 | 内容 |
|---|---|
| 新建 | `SourcesRow.tsx` |
| 验收 | 点角标 chip 高亮；「查看原文」展开片段；无来源时显示「这次没有找到可直接引用的页面」 |

### P3 · 历史分组 + 上下文条（1.5 天）

| 项 | 内容 |
|---|---|
| 新建 | `ConversationList.tsx`、`conversationGroups.ts`、`AssistantContextBar.tsx` |
| 依赖 | 多课程会话数据：并行拉取 `listConversations` 或后端全量接口（见 2.4 第 3 条） |
| 验收 | 按课程分组、两级折叠；当前会话所在组默认展开；切会话恢复历史 |
| 测试 | `conversation-groups.test.ts`（无 scope 字段时的降级、排序） |

### P4 · 改动栏 + 页内浮层（1.5 天）

| 项 | 内容 |
|---|---|
| 新建 | `ChangesPanel.tsx`、`PetStage.tsx`、`petLayout/petPhysics/usePetDrag` |
| 验收 | 空态收起为 44px；有 mock 数据时可展开/预览；桌宠可拖、可召回、位置记忆 |
| 测试 | `pet-drag.test.tsx`（6px 阈值 / 记忆 / 召回） |

### P5 · 后端 B1（0.5 天）+ 前端点亮（0.5 天）

| 项 | 内容 |
|---|---|
| 后端 | 迁移加 3 字段；`ConversationCreate` 接收 scope/note_id；`ConversationRead` 返回；**旧数据 `material/page` 归一到 `course`** |
| 前端 | 创建会话时带上当前 scope；`conversationGroups` 分出 global/note |
| 验收 | 选「锁定笔记」新建的会话出现在对应笔记组；全局会话在顶组 |

### P6 · 后端 B2（0.5 天）+ 改动栏点亮（0.5 天）

| 项 | 内容 |
|---|---|
| 后端 | `note_suggestions` 加 `conversation_id`；写入建议时带上；`GET /conversations/{id}/changes` 按它聚合（存量建议无此字段，不返回） |
| 前端 | 拉取并渲染；「全部写入」逐条 review |
| 验收 | 改完笔记后刷新，行数与状态正确；全部写入后可撤销 |

### P7 · 移动端与收尾（1 天）

- <900：单列、会话抽屉、改动抽屉、输入 sticky。
- 删除旧 `.pet-studio` 死样式；补一轮 390/1024/1440 截图。

**合计：约 8 天**（P0–P4 纯前端 6 天，P5–P6 依赖后端 2 天）。

---

## 五、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 角标误标 | 比不标更糟 | 只按 `lecture_title + page_number` 精确匹配；未命中不编号 |
| 历史分组缺字段 | 只能到课程级 | P3 先按课程分组，P5 点亮笔记/全局；UI 预留层级 |
| 改动栏无数据 | 面板长期空 | 默认收起 + 竖排「改动 0」；P6 再接 |
| 阅读列变窄 | 38–40 字/行 | 收起改动栏时上限 760；不再缩字号 |
| 页内浮层挡输入 | 打字受阻 | 输入框 focus/hover 时浮层让位 |
| 拖拽掉帧 | 手感差 | 坐标只进 ref，rAF 写 `transform`，不逐帧 setState |
| 与坞重复 | 两个助手实体 | 本阶段不动坞；桌宠只在本页，跨页合并留到下一阶段 |

---

## 六、文件树

```
apps/web/src/
├─ pages/
│  └─ AssistantPage.tsx                       [改] 三栏编排
├─ features/assistant/
│  ├─ citations.ts                            [新] 标记解析
│  ├─ CitationText.tsx                        [新] 角标渲染
│  ├─ AssistantThread.tsx                     [新] 消息流
│  ├─ SourcesRow.tsx                          [新] 卡底依据
│  ├─ AssistantContextBar.tsx                 [新] 范围/目标
│  ├─ AssistantComposer.tsx                   [新] 输入卡
│  ├─ ConversationList.tsx                    [新] 两级历史
│  ├─ ChangesPanel.tsx                        [新] 本次改动
│  ├─ TermDialog.tsx                          [新] 术语查询
│  ├─ AssistantMessageContent.tsx             [不动]
│  ├─ AgentSteps.tsx / AgentCards.tsx         [不动]
│  └─ dockLayout.ts                           [不动]
├─ features/conversation/
│  ├─ useConversation.ts                      [不动]
│  └─ conversationGroups.ts                   [新] 分组纯函数
├─ features/pet/
│  ├─ petLayout.ts                            [新]
│  ├─ petPhysics.ts                           [新]
│  └─ usePetDrag.ts                           [新]
├─ components/pet/
│  └─ PetStage.tsx                            [新]
├─ components/AppLayout.tsx                   [不动]
└─ course-assistant.css                       [改] 追加 .ws-*

apps/web/tests/
├─ citations.test.ts                          [新]
├─ conversation-groups.test.ts                [新]
├─ pet-drag.test.tsx                          [新]
└─ assistant-layout.test.tsx                  [新]

apps/backend/
├─ app/db/models.py                           [P5 改] conversations +3 字段
├─ migrations/                                [P5 新] 迁移脚本
├─ app/api/v1/conversations.py                [P5 改] 创建/列表带归属
├─ app/schemas/conversations.py               [P5 改] schema
└─ app/api/v1/agent.py                        [P6 改] GET /conversations/{id}/changes
```

---

## 七、验收口径

```bash
cd apps/web
npm test       # 现有 36 个 + 新增 4 个
npm run build
```

| 步骤 | 手工验收 |
|---|---|
| P0 | 1440 / 1024 / 390 三档截图；无横向滚动；无渐变 |
| P1 | 发一条消息，角标位置正确；点角标有反馈；不露机器标记 |
| P2 | 依据行三段与正文角标一一对应；无来源时提示正确 |
| P3 | 两级折叠；切会话历史正确；当前会话高亮 |
| P4 | 桌宠拖到四角不越界；刷新位置还在；双击/召回归位 |
| P5 | 锁定笔记提问后，会话出现在该笔记组；全局会话在顶组 |
| P6 | 改动行 +/− 正确；预览可展开；全部写入后再撤销 |

---

## 八、与旧计划的关系

旧的实施方案（全站 `PetLayer`、改 `AppLayout`、页面切 `askAgent`）**降级为第二阶段**。本计划只做答疑页，桌宠不跨页、页面继续用 `ask`、不动坞。等页面稳定后再评估是否把桌宠提到外壳、把页面切到 agent 链路。

---

## 九、实施状态（2026-10-20 落地）

| 步骤 | 状态 | 说明 |
|---|---|---|
| P0 三栏骨架 | ✅ | 240 历史 + 阅读列 + 改动栏（收起 44） |
| P1 对话主线 + 角标 | ✅ | `citations.ts` + `CitationText`；角标按首次引用顺序连续编号 |
| P2 卡底依据行 | ✅ | chips + 查看原文；未命中标记降级为纯文本，不编号 |
| P3 历史两级 | ✅ | 课程 → 整门课程 / 笔记；无 scope 数据时降级为课程级 |
| P4 改动栏 + 页内桌宠 | ✅ | 空态收起；`features/pet` 浮层（PetAvatar） |
| P5 B1 会话归属 | ✅ | `conversations` + `scope/note_id/note_title`；词表统一 course/global/note；迁移 `c5a7b2e91f34` |
| P6 B2 改动聚合 | ⏸ 暂缓 | 本页走 `ask` 链路，不产生 `note_suggestions`；改动栏维持空态 |
| P7 移动端收尾 | ✅ | 390 / 1024 / 1440 无横向溢出；无 `pet-studio` 死样式可删 |

### 落地要点

- **角标编号**：改为「该来源首次被引用的顺序」（1、2、3…），不再等于它在 `sources` 里的下标；同一来源多处引用复用同一号。这样卡底 chips 与正文角标一一对应，不会出现只亮一个「4」的断号。
- **匹配不到就删**：如模型引用了不存在的讲次（例如检索结果全是第 1 讲，却写「第 2 讲」），该标记降级为纯文本，不猜编号。
- **后端词表**：`ConversationCreate` 新增 `scope / note_id / note_title`；`default_scope` 仍接受 `material / page`（老客户端不 422），但一律归一为 `course`。只有 `scope='note'` 才保留笔记快照，其余置空。
- **列表契约**：`ConversationRead` 返回 `scope / note_id / note_title`；前端 `ConversationList` 已能按 scope 分组，数据到位即点亮「笔记 / 全局」两层。
- **移动端测法**：Windows 上的 headless Chrome 会把窗口宽度钳到约 512px，直接用 `--window-size=390` 截出来是「被裁掉」的假象；真 390 需用 CDP `Emulation.setDeviceMetricsOverride`，实测 `scrollWidth = 390`，无溢出。

### 已知限制 / 下一阶段

1. **「笔记 / 全局」两层仍为暗态**：答疑页的 scope 恒为 `course`；笔记归属来自悬浮坞 / 笔记页的 agent 会话，需在 `ensureConversation` 传入 scope 才能点亮。本阶段按计划不动 `useConversation` / `AssistantDock`。
2. **改动栏真实数据需 P6**：`note_suggestions` 加 `conversation_id` 并做聚合接口，且要 agent 链路真的产出建议；`ask` 链路天然不产出，所以这里保持空态是正确行为，不是缺陷。
3. **桌宠浮层只在答疑页**：跨页悬浮仍待改 `AppLayout`。
