# NoteBuddy 初版架构

## 当前目标

初版先实现本地单用户 Web Demo：

```text
课程笔记本 → 讲次章节 → 逐页解析 → PageBlock 来源引用 → 小节笔记/概念关系 → 检索问答
```

基础知识点提取、可编辑笔记、版本保护和可选外部模型调用已经接入；语义 Embedding 通过可配置的兼容接口启用。

## 运行边界

- `apps/web`：React + TypeScript + Vite，负责三栏笔记工作区。
- `apps/backend`：FastAPI，负责课程、文件、解析任务、知识图谱、笔记版本、模型调用和检索 API。
- `data`：本机数据目录，不提交到 Git。
- SQLite：业务数据真实来源。
- 向量索引：`retrieval_chunks` 中作为可重建的检索派生数据，不承载用户笔记真相。
- 外部模型：`app/ai/deepseek.py` 只读取环境变量中的 API 配置；模型失败时回退到本地规则，不暴露密钥。
- Markdown 数学排版：后端提示词约束 LaTeX，前端使用 `remark-math` + `rehype-katex` 渲染。

## 会话、来源与搜索边界

- `app/services/conversations.py` 负责两种会话入口共用的消息与证据事务，以及会话加载；传统问答和 Agent SSE 分别保留自身的生成与传输逻辑。
- `app/services/assistant_sources.py` 负责将实时检索结果及已保存证据转换为来源卡片结构。`app/services/terms.py` 提供术语原文查询，HTTP 路由与 Agent 工具共用。
- `app/web_search/service.py` 复用既有 `app/web_search` 策略，集中执行缓存、供应商审计、结果审核和课程内网络来源保存。传统问答与 Agent 工具各自决定搜索词和回答策略。
- Agent 工具的只读查询在 `app/ai/agent_read_tools.py`，笔记小节编辑算法在 `app/ai/note_edits.py`；`agent_tools.py` 保留工具定义、分发及建议生成入口。
- 前端答疑页与答疑坞共用消息 Markdown 和来源卡片组件，同时保留各自布局；设置业务状态由独立 Hook 管理。
- `app/db/models.py` 保留 ORM 兼容导出，森林相关表定义已移至 `app/db/forest_models.py`；表名、关系与迁移历史不因此改变。
- 本地执行器连续处理三个资料任务后检查森林任务，避免持续的资料队列使森林任务一直得不到领取。

## 阶段一运行与数据边界

API 只登记待处理资料任务；`app.workers.runner` 是同仓库的本地单实例任务执行器，不提供第二套 HTTP API。`scripts/dev.ps1` 先迁移数据库，再启动执行器、API 与 Vite。执行器用 OS 文件锁避免并行处理，进程重启后把上次中断的处理中任务明确标为可重试失败。上传时使用临时文件、PPTX 容器检查、原子落盘和哈希；相同课程的重复文件默认提示，允许显式作为新讲次导入。

SQLite 是业务真相，Alembic 负责版本迁移；迁移与逻辑删除前使用可校验检查点。见 `docs/migrations.md`。外部服务状态区分“已配置”和“连接成功”，连接测试需要用户主动触发。

## 任务状态

资料解析任务必须经过：

```text
pending → processing → completed
                    ↘ failed
```

任务状态持久化到数据库，前端通过 `GET /api/v1/jobs/{job_id}` 查询。后续接入 SSE 时保持同一任务模型。

## 知识点关系为什么必须两遍处理

`app/knowledge/extractor.py::extract_material_knowledge` 分两遍执行，这不是风格选择，而是**正确性要求**。

关系生成本质上需要「全局视图」：第 1 页提到的知识点，可能到第 40 页才被建立。早期实现是边建节点边连边：

```python
for page in pages:
    node = create_node(...)          # 建当前页的节点
    ensure_relations(db, node, ...)  # 立刻连边
```

而 `ensure_relations` 对找不到的目标节点是 `continue`（跳过，不凭空建节点）。于是：

1. 处理第 1 页时，第 40 页的知识点**还不存在** → 关系被丢弃
2. 处理第 40 页时，第 1 页早已处理完，**不会回头补边**

两边都落空，`knowledge_edges` 恒为 0——「知识树」于是只剩一堆孤立节点。

修复方案：

```python
# 第一遍：建立全部节点与笔记，把待连的关系收集起来
for page in pages:
    node = find_or_create_node(...)
    pending_relations.append((node, draft.get("relations")))
db.flush()                            # 确保本次新建的节点可被查询

# 第二遍：所有节点就位后统一连边
for node, raw_relations in pending_relations:
    ensure_relations(db, course_id, node, raw_relations)
```

配套加入**名称归一化**（`normalize_name`）：模型对同一概念可能给出「矩阵」「矩阵（一）」「矩阵(上)」等不同写法，精确字符串匹配会让它们变成两个孤立节点、关系也连不上。归一化只做保守折叠——统一宽度、折叠空白、小写化、去掉序号/卷次后缀——**刻意不做模糊匹配**，避免把「导数的定义」和「导数的几何意义」错误合并。测试中用参数化用例同时锁住「该合并的」与「不该合并的」两侧。

回归测试见 `tests/test_knowledge_relations.py`，其中 `test_cross_page_relation_resolves_after_all_nodes_exist` 精确复现上述 bug 场景。

## 自然手绘知识森林（2026-10-11）

新增全局 `/forest` 场景。React 管理 SVG 节点，`d3-zoom` 与 `d3-selection` 管理视口，`d3-shape` 生成植物曲线。装饰性树形和业务叶子分层，叶子绑定现有 Note ID；森林只按可见区域读取笔记本目录，避免加载所有课程正文。课程层级、顺序、学习状态与独立修订保存在 `ForestCourseProfile`，视口和布局缓存保存在浏览器。

`CrossCourseRelation` 独立表示两门课具体笔记之间的藤蔓，绑定两端课程、笔记版本和来源。2026-10-11的 pending 后审核方案是历史行为；2026-10-15更新为独立持久任务校验来源与版本后直接生效，`activation_mode` 区分 automatic/manual，`evidence_fingerprint` 追踪来源变化。旧 pending 由执行器补验，迁移不调用模型。失效关系隐藏后重分析，用户隐藏保留 rejected，自动任务不恢复。原 `KnowledgeEdge` 仍仅用于课程内知识关系，原答疑接口继续校验课程归属。

`CurriculumImport` 保存 PDF/DOCX 或文本导入、原文件、来源位置、模式、告警与预览行；确认后创建或关联课程。培养方案不进入 Material/课程讲次。新增 `ForestJob` 持久队列由 `app.workers.runner` 同一独立进程处理，承担培养方案解析与跨课程候选生成。资料成功生成笔记后登记任务，API 不在请求进程内执行 AI。

全量备份与迁移/删除检查点保留培养方案原文件；单课程备份过滤全局培养方案和外课引用。旧库升级使用新 Alembic 迁移，保留原节点、笔记正文、来源、版本和入口。

设计见 [专项设计](superpowers/specs/2026-10-11-knowledge-forest-design.md)，实际验证状态见 [专项交接](handoffs/2026-10-11-knowledge-forest.md)。

## 后续扩展

## 当前数据关系

课程包含多个 Notebook，Material 是所属本的章节，Note 是小节。`Notebook.order_revision` 对本内章节重排做乐观并发保护，上传、删除、恢复也递增所属本版本。旧 `Course.notebook_order_revision` 保留兼容。`Material.chapter_order` 保留讲次顺序，`Note.material_id + section_key` 定位本讲位置，`section_order` 控制小节顺序。Notebook/Note 的 `tree_slot` 持久分配，不因目录重排改变；同名点跨讲、跨本保留独立正文与Note ID。`KnowledgeNode.notes` 仍一对多、概念课程级复用。

`NotebookReadingPosition` 按本保存在 SQLite，记录章节、Note ID、chapter/book模式、0..1小节相对偏移及独立CAS版本。阅读正文稳定后恢复一次，深链优先，滚动节流保存、切换离开补存；网络失败或409保留待重试位置并暂停后续写入。`Course.last_opened_at` 只由实际访问写入；首页选最近三课，浏览器返回保留原集合和相机。

首页和森林共用 `KnowledgeTreeScene`，仅课程集合与初始布局不同。正常总览最多6本/枝各6真实叶标签，放大/目录/搜索/藤蔓端点临时透镜可达全部Note。相机按实际画布宽度显示1–3棵，可见及邻近课程才挂载目录。绘制为本地3根干/6叶片atlas与动态SVG；主枝沿三次曲线法向渐细，从同主干变体atlas采样不透明树皮，以14个切线方向的渐隐重叠段裁进轮廓，固定纹理尺度，无额外图片资源。叶柄从主枝不同位置连接原叶坐标。木质绘制与交互分层，枝基由树干覆盖，标签/hit独立；学习状态仅给叶片配色，不表示掌握度。使用已有D3模块，无新增运行依赖或远程字体。

前端 `KnowledgeTreeView.knownNotebookIds?` 随既有session画布快照保存已加载课程的本ID基线，空课也保留[]。新增Notebook依据持久槽位生成独立枝；创建后经上传页返回同entry时，和基线相比仅新枝装饰层生长600ms，不缩放操作区、叶坐标或相机。首次无基线/旧缓存不全树动画，普通目录刷新不重播，reduced-motion直接显示；6本总览/完整目录规则不变。

自动关联任务保存完整受影响源ID/版本/证据指纹集合，按每批≤30源、≤18外课候选执行；保存或生成合并尚未领取的任务，重试保留进度并复核快照，提交前再核对引用和修订。related对称去重，先修保留方向，无配置时明确failed。详细API与验证边界见 [接口](api.md) 和 [交接](handoffs/2026-10-14-knowledge-tree-home.md)。

迁移先创建校验检查点；移除旧 notes 概念唯一约束时暂时关闭 SQLite 外键并检查迁移后引用，保留修订、建议和来源。只有来源归属单讲的旧笔记回填 material_id，多讲/无来源旧笔记保留历史整理。首次重解析在唯一可匹配的位置接续旧 Note ID；歧义旧笔记不自动拆分。多正文库拒绝有损降级。

```text
Course
 ├─ Notebook ─┬─ Material ─ MaterialPage ─ PageBlock ─ SourceRef
 │            │                          └─ RetrievalChunk
 │            └─ NotebookReadingPosition
 ├─ KnowledgeNode ─ KnowledgeEdge ─ KnowledgeNode
 │       └─ Notes（各讲独立）─ NoteRevision
 └─（知识点和笔记通过多对多关系引用 SourceRef）
```

`Course` 的 ORM 级联供显式物理清理使用；公开删除接口实际执行带检查点的软删除，正文和来源保留以便恢复。

`Note.user_locked=true` 后，后续资料解析只会补充来源和知识节点摘要，不会覆盖用户笔记正文。`revision_number` 用于乐观并发保护，前端保存时必须携带当前版本号。

## 已实现 API

| 能力 | 接口 |
|---|---|
| 创建课程 | `POST /api/v1/courses` |
| 课程列表 | `GET /api/v1/courses` |
| 课程重命名 | `PATCH /api/v1/courses/{course_id}` |
| 课程软删除（带检查点） | `DELETE /api/v1/courses/{course_id}` |
| 课程知识图谱 | `GET /api/v1/courses/{course_id}/knowledge-graph` |
| 课程笔记 | `GET /api/v1/courses/{course_id}/notes` |
| 笔记编辑 | `PATCH /api/v1/notes/{note_id}` |
| 笔记版本 | `GET /api/v1/notes/{note_id}/revisions` |
| 笔记来源 | `GET /api/v1/notes/{note_id}/sources` |
| 课程范围 RAG | `POST /api/v1/courses/{course_id}/assistant` |
| 配置状态（脱敏） | `GET /api/v1/settings` |
| 配置写入（白名单） | `PATCH /api/v1/settings` |

## 设置面板安全模型

`apps/web` 左下角齿轮打开设置抽屉，数据来自 `GET /api/v1/settings`（只返回布尔与长度提示，**永不回传密钥明文**）。写入走 `PATCH /api/v1/settings`，实现在 `app/core/settings_store.py`，约束如下：

1. **白名单**：仅 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT_SECONDS`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`NOTEBOOK_MAX_UPLOAD_MB` 可直接写入；`NOTEBOOK_DATA_DIR`、`allowed_extensions` 等结构项永不可改。非白名单键在 Pydantic 层就以 `extra="forbid"` 拒绝。
2. **本地密钥写入**：本地单用户模式默认允许从设置面板写入 `DEEPSEEK_API_KEY` / `EMBEDDING_API_KEY`；`NOTEBOOK_ALLOW_SECRET_WRITE=false` 可显式关闭。若配置了 `NOTEBOOK_SETTINGS_TOKEN`，请求头 `X-Notebook-Settings-Token` 必须匹配（`secrets.compare_digest` 常量时间比较）；未配置 token 时，本地模式允许写入。远端共享部署必须另外设置访问控制，并显式决定是否禁用密钥写入；口令校验不能代替整个 API 的身份认证。
3. **写入前置校验**：写入新的 DeepSeek Key 前，先调用服务端 `/models` 探活。401/403 直接以 **422 拒绝写入**，**绝不覆盖仍然可用的旧密钥**；网络不可达时降级为 warning 并放行（可设 `NOTEBOOK_SKIP_KEY_VERIFY=true` 完全跳过）。
4. **注入防护**：拒绝含换行符的值（防止向 `.env` 注入额外键）、拒绝 `VITE_` 前缀（防止密钥被前端打包）、模型名仅允许字母数字连字符、URL 必须 `http(s)://`、数值有区间约束。
5. **可回滚且不破坏原文件**：写盘采用"原地改写托管键 + 保留全部注释与未托管键"的策略，而不是整体重写；写入前备份 `.env` 到 `data/backups/env-<时间戳>.bak`，仅保留最近 20 份（备份含明文，避免无限堆积），再用临时文件 `os.replace` 原子替换。
6. **密钥不可反向读出**：状态接口只返回 `**** · 共 N 位`，不保留任何真实前缀（早期版本保留前 4 位，对已知 `sk-` 前缀的厂商等于泄露熵，已修正）。

### 密钥不进版本库

`.env` 与 `data/` 均在 `.gitignore` 中，且仓库提供 `.githooks/pre-commit`（启用状态须以 Git 配置核对）。`.githooks/pre-commit` 提供四道拦截：① 暂存区出现 `.env` 实体文件 → 拒绝（`.env.example` 例外）；② 暂存 `data/` 下的数据库/课件/备份 → 拒绝；③ 新增行匹配 `sk-xxx`、`ghp_`、`AKIA`、`BEGIN PRIVATE KEY` 等密钥特征 → 拒绝（示例占位值白名单放行）；④ `.env` 脱离 ignore 状态 → 拒绝。确需绕过时用 `git commit --no-verify`。

安全测试见 `apps/backend/tests/test_settings_security.py`。

## 课程生命周期

重命名只接受 name 字段，空白名称被拒绝。课程及资料删除先检查活动任务，再创建文件校验检查点，标记 deleted_at；列表隐藏已删除记录，恢复接口解除标记。公开删除不会清除用户正文、来源或原文件。ORM 物理级联与公开软删除是不同操作。

## 后续工作

1. AI 选页补生成及明确的重点/难点处理。
2. 知识树专项视觉设计和真实跨讲语义质量验收。
3. 收起式应用内桌宠、阅读笔记与连续追问上下文、无课程证据时的通用解释。
4. 真实 PPTX/PDF/DOCX 与 OCR、公式、来源质量验收。
5. 外部模型与 Embedding 联调、性能评测、Electron 交付。
