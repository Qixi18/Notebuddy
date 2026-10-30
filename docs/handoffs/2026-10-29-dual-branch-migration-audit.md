# 双旧分支迁移：审计、修复与回归补测（2026-10-29）

## 本轮目标

在 `feat/debug-integration` 上，按交接文档完成 `feat/home-knowledge-forest` +
`feat/agent-dialogue` 迁移后的缺陷审计与缺口补测：数据边界审查、revision 冲突与
草稿保护、删除恢复、跨课程隔离、幂等与并发竞态、SQLite 临时库 upgrade/downgrade。

## 分支与提交

- 分支：`feat/debug-integration`
- 起点：`e7af411`（本轮之前的最后一个提交）
- 本轮提交：见文末「本轮提交」
- 未 push、未改 `main`、未建 PR。此前暂存的 `.gitignore` / `README.md` / `docs/**`
  用户改动保持原样留在暂存区，未纳入本轮提交。

## 修复的实际缺陷

### 1. 批量应用修改建议没有刷新森林关系

`POST /courses/{course_id}/notebook-edit-suggestions/apply-all` 走
`write_document(..., origin="ai_suggestion")` 时漏了 `refresh_relations=True`，
而同一功能的单条确认路径（`review_edit_suggestion`）、自动保存、历史恢复三处都传了。
后果是批量合并后正文变了、森林关系候选没重建，跨课程关系停留在旧快照。

修复：补齐参数，与其余三个写入口一致。

### 2. 自测卷「同一答案重试幂等」在并发下会重复落行

`grade_answers` 的幂等判定读的是「该题最近一次作答」，然后插入新 `quiz_attempts`。
读与写之间没有任何串行化，两条完全相同的并发请求会都读到「无历史作答」，各插一行。
本轮先写并发测试复现（两个线程同时提交相同答案 → `assert 2 == 1` 失败），再修。

修复：在判分循环前对所属自测卷发一次等价写
`UPDATE quizzes SET status = status WHERE id = :id`（`synchronize_session=False`）。
SQLite 会持有写锁到本次事务 commit，并发提交因此排队；保留「最近一次作答」的原始
语义，没有改成「历史上答过同一答案就永远幂等」——那样用户改天再答同一选项会拿到旧判分。

### 3. 迁移 `e29a10c7f501` 不可重入，回填逻辑实为空转

- Alembic 在同一事务里执行 DDL，中途失败只留部分结构；原实现重跑会撞
  `duplicate column name` / `table already exists`，无法续上。
- 原实现把 4 个索引的创建写在「建表」分支内，半应用状态（表在、索引缺）会永久漏建。
- 原 `_backfill_review_artifacts()` 看起来在迁移旧学习建议，但父版本 `d9e4a7b21c60`
  根本没有 `suggestions_json` 列，该列是本迁移新建的，升级后全为 NULL——对干净库
  它永远空转。文档里必须写明，否则后人会误以为历史建议已被迁移。

修复：升级/降级都按探测结果只处理缺失对象（表、列、索引分别判断）；回填函数补上
明确说明，保留其真实价值——**已经带该列的库**才会真正搬迁数据，且按 id 查重可重跑。

### 4. `test_mineru_integration` 裸 `import pymupdf` 导致整文件硬失败

`pymupdf` 是可选依赖（`pdf_text` 走 `pypdfium2` 回退），仓库其他四处测试都用
`pytest.importorskip("pymupdf")`，只有这一处是裸导入，干净环境直接 `ModuleNotFoundError`。
修复为函数级 `importorskip`：只跳过这一个用 pymupdf 构造 fixture 的用例，同文件其余
用例照常运行。

## 新增回归测试

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_agent_learning_migration.py` | 临时 SQLite 上 upgrade → 回填 → downgrade → 再 upgrade；历史库回填（中文标题逐字、确定性 id、非学习产物被忽略）；干净库不回填；半应用状态续跑并补建索引；全程校验 `document_json` 与 `document_revision` 不变 |
| `tests/test_notebook_edit_suggestion_review.py` | 拒绝确认后正文与 revision 一字不动；`expected_revision` 不符返回 409 且建议仍 pending；重复确认被拒；apply-all 合并同本多条建议只推进一次 revision；重复编号 422；跨课程 404；用户先改正文则建议置 stale 且用户正文保留；已处理建议 409；已删除 Notebook 的建议 404；删除为软删除、恢复后正文与 revision 原样、恢复后仍可审核建议 |
| `tests/test_quiz_idempotency.py`（扩充） | 两个线程并发提交相同答案，最终只有一条 attempt 且两边判分一致 |
| `tests/test_review_artifacts.py` | 复习产物按课程隔离；移出复习是软移除且可恢复；收藏与 kind 过滤；不存在的产物更新返回 None |
| `tests/test_agent_tool_scope_gates.py` | 学习技能在 `allow_quiz=False` 时即使被硬调也必须拒绝且零副作用；无模型时报失败、不落半成品；无素材时先拒再谈模型；`load_notebook` 拒绝跨课程与已删除笔记；会话消息搜索按课程隔离、LIKE 通配符已转义 |
| `apps/web/tests/mistake-book.test.tsx` | 复习面板此前**零前端测试**：按课件分组渲染错题与讲评、收藏翻转并落库、移出复习需二次确认且只移除该题、复习提纲子页带 `include_dismissed` 拉取并可恢复、搜索按题干筛选、追问/重练提示词带上原题与答案、Esc 关闭、空态与加载失败都有界 |

## 本轮实际执行的验证

全部在本机真实执行，命令与结果如下（未删除或弱化任何断言）。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 后端静态检查 | `uv run ruff check app tests`（`apps/backend`） | All checks passed |
| 后端全量测试 | `uv run pytest -q` | **240 passed, 8 skipped**（本轮前基线：216 passed, 7 skipped, 1 failed） |
| 前端单测 | `npm test`（`apps/web`，含导航 47 例） | **303 passed / 60 files**（本轮前 294 / 59） |
| 前端类型检查 | `npx tsc -b --noEmit` | 通过 |
| 前端构建 | `npm run build` | 成功；仅已知的 chunk > 500 kB 体积告警 |
| 迁移升级/回滚 | `test_agent_learning_migration.py`（临时目录，非用户库） | 2 passed |
| 真实服务冒烟 | 一次性脚本：临时 `NOTEBOOK_DATA_DIR` → `alembic upgrade head` → `uvicorn` → httpx 打真实端点 | 全通过（脚本已删除，输出记录见下） |
| 真实浏览器联调 | 临时数据库 + `uvicorn:8000` + `vite:5173`，headless Edge 157 经 CDP 打开页面并**真实点击** | 见下节 |

## 真实浏览器联调（本轮新增，不含模型）

环境：`NOTEBOOK_DATA_DIR` 指向临时目录、`DEEPSEEK_API_KEY` 置空、后端 `uvicorn`
跑在 `127.0.0.1:8000`、前端 `vite` 跑在 `127.0.0.1:5173`、headless Edge 157 +
CDP 脚本驱动真实点击。全程未使用任何模型凭据，未触碰用户 `data/`。

看过的页面（截图逐张用读图工具看过，不是只看返回码）：

- 首页：侧栏、标题区、课程花园空状态正常渲染；
- 笔记本编辑页：`document_json` 正文、两个标题的目录（`第一章 算法复杂度` /
  `1.1 常见阶`）、`已保存 22:59`、工具栏全部正常；
- 答疑页：桌宠前言、建议提问、输入区、右侧「待审」入口正常；
- 森林页：课程树与课程铭牌「数据结构与算法」渲染正常，缩放/图例/地图正常。

点出来的交互结论：

1. **待审建议卡片真实渲染**在会话内，右侧显示「待审 1」。
2. **真实点击「忽略」**后：卡片消失、提示「已忽略这条修改建议。」、右侧变「待审 0」，
   页面无报错。随后直接查 API 复核：
   - `GET .../document` → `revision` 仍为 **1**（未推进）；
   - 正文 JSON 中**不含**建议文本；
   - `notebook-edit-suggestions` 待审 **0** 条、已拒绝 **1** 条，`status=rejected`。
   这就是自动化测试之外、用真实 UI 走通的「拒绝确认前正文不变」。
3. **真实点击「复习」**：面板打开，题目页显示错题（我的答案 `O(n²)` / 正确答案
   `O(1)` / 解释），并带收藏、标记、移出复习与「让 AI 讲讲这道题」「重练同类」。
4. **真实点击「复习提纲」**子页：复习产物 `复杂度复习提纲` 正常渲染（0/1 进度、
   模块「阶的比较」优先级「高」、条目与来源），收藏/移出复习可用。

### 数据边界审计补充（`e7af411` 其余文件逐行看过）

上面几条是从行为上修的，这一轮把上次没逐行看的后端 diff 补完，结论如下
（**未发现越权或绕过确认写正文的路径**，但其中三处当时没有任何测试，已补）：

- `agent_read_tools._search_course` / `_read_notebook` / `_explain_term`：`scope="note"`
  时强制走 `locked_notebook_id`，显式传别的 `notebook_id` 直接拒绝；指定 `material_id`
  时用 `material_in_course` 校验归属。
- `agent_tools.execute_tool` 是**双重闸门**：先按 `allow_quiz` 拒掉学习技能，再按
  `build_tool_specs` 生成的白名单拒绝越界工具——所以模型即使幻觉出一个未授权的
  工具调用，也执行不了，不只是「提示词里没给它」。
- `load_notebook` 同时拒绝已删除与跨课程笔记；`_propose_notebook_edits` 用
  `notebook_id` 与 `editable_notebook_id` 比对，只能对当前打开的笔记提案。
- `retrieval.retrieve(notebook_id=…)` 在锁定笔记时把课件检索结果置空，
  `_retrieve_notebooks` 同时按 `course_id` 与 `notebook_id` 过滤，跨课程取不到。
- `search_course_messages` 按 `Conversation.course_id` 过滤，且
  `icontains(..., autoescape=True)` 转义 LIKE 通配符（已用 `%` / `_` 查询验证）。

### 三档宽度实测（headless Edge + CDP 设备指标）

用 `Emulation.setDeviceMetricsOverride` 在 390 / 768 / 1440 三档打开笔记本页与答疑页，
并用 `scrollWidth - clientWidth` 判定真实横向溢出：

| 页面 | 390 | 768 | 1440 |
| --- | --- | --- | --- |
| 笔记本编辑页 | 无溢出 | **溢出 9px**（`.notebook-document-top-actions` / `.notebook-document-quick-actions`） | 无溢出 |
| 答疑页 | 无溢出 | 无溢出 | 无溢出 |

768 那 9px 的成因：`NotebookPage.css` 的断点是 `max-width: 1120px` 与 `max-width: 760px`，
**761–900px 落在空档**——该区间里 `.notebook-document-top-actions` 没有宽度约束，
只有子项 `.notebook-document-quick-actions { max-width: 48vw }`，于是顶部操作条把
页面撑出横向滚动条（截图 `notebook_768.png` 可见右下横向滚动条与右侧被截断的「查看…」）。

经 `git log` 确认 `apps/web/src/pages/NotebookPage.css` 在 `31e87d7..HEAD` 内**未被修改**，
即这是 main 上就存在的问题，不是本次迁移引入。**本轮没有改它**：修它要动共享设计 CSS
（收紧断点或让操作条在区间内横向滚动），属于需要视觉复核的设计改动，不应顺手塞进
迁移审计里。留作明确的后续项。

### 答题卡作答动线（真实点击，不依赖模型）

自测卷卡片由**已落库的会话建议**驱动渲染（种一条带 `suggestions_json` 的历史消息，
不需要模型出题），判分走服务端确定性逻辑。实测：

| 观察点 | 结果 |
| --- | --- |
| 卡片从历史恢复 | 显示「自测卷 / 复杂度自测 / 已判 0/2」，选项齐全 |
| **判分前是否泄题** | 页面上**没有**正确答案或解释（`showsAnswersUpFront: false`） |
| 点错选项 `O(n²)` | 立即判分：进度变「已判 1/2」，该题 class 变 `quiz-item is-wrong`，错项标 ✗、正确项标 ✓、其余置灰、讲评出现、「讲讲这道题」按钮出现 |
| 重复点击 | 该题选项 `disabled`，不会产生第二条作答 |
| 错题本 | `GET /quiz-mistakes` 恰好 1 条，题干匹配 |
| 控制台 | 无异常 |

截图：`%TEMP%\nb_shots\quiz_answer.png`。

### 森林生长动画（真机验证，含一个容易误读的设计细节）

**先记一个坑**：在全新会话里首次打开首页，花园**不会**播放生长动画——这不是缺陷。
`growth/ledger.ts` 的 `observeDirectory()` 对每个目录第一次只**播种基线**
（`if (initialized && !knownBook)`），不产生动画事件；动画只针对「相对已见状态的新增」。
我第一次用「首屏看有没有动画」的测法，得到 7 秒内仅 48ms 的挂载变化、零动画，差点
把它写成缺陷——查了 ledger 才确认是设计如此。

正确的验证方式：同一 tab 内先加载一次（播种基线）→ 通过 API 新增一本笔记 → 重载 →
观测。实测：

| 阶段 | 花园子树变化 | 变化跨度 | 峰值并发动画 | growth 类 |
| --- | --- | --- | --- | --- |
| 首次加载（播种基线） | 33 次 | 50ms | 0 | 0 |
| 新增笔记后重载 | 57 次 | **1693ms** | **6** | 1 |

两帧截图（重载后 1.5s 与 2.7s）像素差异 bbox 覆盖整片花园 `(259,73)-(1363,728)`，
说明枝干/藤蔓确实在推进。`document.visibilityState === "visible"`、
`prefers-reduced-motion: false`，闸门未拦。截图：`%TEMP%\nb_shots\forest_growth_early.png`
与 `forest_growth_late.png`。

### 阅读位置保存与恢复（真机验证通过）

在 1440 档把正文容器滚到 900，抓网络确认：`PUT .../reading-position` 发出，
请求体 `{"block_id":"p-3-4","mode":"book","section_offset":0.288…,"expected_revision":0}`，
响应 200；随后 `Page.reload`，9 秒后读数 **`scrollTop: 900`，置顶块 `p-3-4`**，
与保存值一致，控制台无报错。

> 更正：本轮第一次探针曾报「重载后位置为 0」，那是**探针自己的问题**——它只赋值
> `scrollTop` 而没有派发 `scroll` 事件，前端 `capture` 监听器因此没触发。补上
> `dispatchEvent(new Event('scroll'))` 后保存与恢复都正常。特此写清楚，避免把这个
> 假阴性当成产品缺陷。


### 联调中发现但**未修改**的一点（需产品决定）

答疑页在课程只有 Notebook 正文、没有上传课件时，会显示「这门课还没有可检索的资料。
上传并解析课件后，回答才会引用课程内容。」该文案由 `materials.length === 0` 触发，
而 Agent 实际上能通过 `read_notebook` / `search_course` 读到 Notebook 正文
（`test_search_course_and_read_notebook` 覆盖）。经 `git log -S` 确认该文案在
`31e87d7`（main）就存在，**不是本次迁移引入的回归**，属既有文案与实现不完全对齐。
改产品措辞属于产品决策，本轮不动。

真实服务冒烟观察到的事实（临时数据目录 `nb_smoke_*`，跑完即删）：

- 建课、建本、写正文得到 revision 1；用过期 revision 再写返回 409；
- `GET /courses/{id}/quizzes` 下发的题目**不含** `answer`；
- 判分 0/1 正确；同一答案重试后 `quiz_attempts` 仍只有 1 行；
- 错题本只返回本课程的题；`PATCH /quiz-items/{id}/flags` 生效；
- `GET /courses/{id}/notebook-edit-suggestions` 返回空列表；
  `apply-all` 传不存在的 id 返回 404，传空数组返回 422。

### 跳过的 8 个用例（环境原因，非代码缺陷）

- 4 个：`pymupdf` 未安装（可选依赖，模块级 `importorskip`，`pdf_text` 走 pypdfium2 回退）。
- 4 个：真实 OCR 模型集成，需 `NOTEBOOK_RUN_REAL_OCR=1` 且本机模型可用。
- 1 个：真实课件不在仓库中。

## 未完成 / 不能宣称验收

按 `agent.md` 第 4 节要求，以下三件事必须分开表述。本轮只做到「代码已改」与
「本地检查通过」，以下**没有**做到：

1. **真实模型验收未做**。Agent 问答、复习提纲、易混概念、真实出题与简答判分，
   都需要授权模型配置。本轮没有读取、也没有使用 `.env` 里的任何凭据；确定性的
   schema 校验、判分、来源引用测试覆盖到了，但不等于真实模型质量验收。
2. **真实浏览器 UI 验收：只剩主观判断**。已验证：四类页面渲染、拒绝待审建议后
   正文不变、复习面板错题与复习提纲、答题卡点选即判分且判分前不泄题、重复点击不产生
   重复作答、三档宽度溢出实测、阅读位置保存与恢复、森林生长动画在「有新增内容时」
   确实播放。**仍未做**：动画观感的确认（时长/节奏是否舒服）、390/768 窄屏排版的
   人工判断、「重练同类」触发出题（需要模型）。
   另发现 **761–900px 断点空档导致笔记本页顶部操作条溢出 9px**（main 既有，非本迁移
   引入，未修，成因见「三档宽度实测」）。
3. **真实资料解析未做**。端到端图片/PDF 到 DocumentIR 的用例使用确定性 fixture，
   不代表 MinerU / 真实 OCR 引擎与真实课件质量。

其他限制：

- 本轮**没有触碰真实用户数据库**（`NOTEBOOK_DATA_DIR` 默认的 `data/`），所有迁移
  验证都在临时目录。用户库是否已升级到 `e29a10c7f501`、以及其 `alembic_version`
  状态，本轮未检查——需要单独确认后再在真实库上跑 `alembic upgrade head`。
- 迁移改为可重入后，若某库已由旧版本应用过部分结构，重跑会补齐缺失对象；但
  若该库的 `alembic_version` 指向未知 revision（例如曾跑过旧 Agent 分支的迁移链），
  Alembic 会先报「找不到 revision」，需要人工处理，不在本迁移能覆盖的范围。
- 前端打包体积告警是既有问题，本轮未处理。

## 复现方法

```powershell
cd apps\backend
uv run ruff check app tests
uv run pytest -q
uv run pytest tests\test_agent_learning_migration.py -q

cd ..\web
npm test -- --run
npm run build
```

数据库迁移只在临时目录验证：

```powershell
$env:NOTEBOOK_DATA_DIR = Join-Path $env:TEMP ("nb_mig_" + [guid]::NewGuid())
cd apps\backend
uv run python -m alembic upgrade head
uv run python -m alembic downgrade d9e4a7b21c60
```

真实浏览器联调（同样用临时数据目录，**不要**把 `NOTEBOOK_DATA_DIR` 指向 `data/`）：

```powershell
# 1) 后端：8000 是 vite 代理里写死的目标端口
$env:NOTEBOOK_DATA_DIR = Join-Path $env:TEMP "nb_browser_smoke"
$env:DEEPSEEK_API_KEY = ""
cd apps\backend
uv run python -m alembic upgrade head
uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 前端
cd ..\web
npm run dev            # http://127.0.0.1:5173

# 3) 本机没有 Chrome，用 Edge 的 headless 模式
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  --headless=new --disable-gpu --user-data-dir="$env:TEMP\nb_edge_profile" `
  --window-size=1440,900 --virtual-time-budget=12000 `
  --screenshot="$env:TEMP\home.png" "http://127.0.0.1:5173/"
```

需要点击的交互用 CDP：以 `--remote-debugging-port=9333` 启动同一个 Edge，从
`http://127.0.0.1:9333/json/list` 取页面 `webSocketDebuggerUrl`，用 Node 内置
`WebSocket` 发 `Runtime.evaluate` 执行 `el.click()`，再用 `Page.captureScreenshot`
取图。本轮用的三个一次性脚本（勘察/点击流程/通用点击）跑完即删，没有留在仓库里。

## 本轮提交

（见本文件所在提交；提交只包含后端修复与新测试、本 handoff 文件，不含用户暂存的
`.gitignore` / `README.md` / `docs/**` 改动。）
