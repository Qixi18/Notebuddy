# NoteBuddy 软件工程详细设计

| 项目 | 内容 |
|---|---|
| 文档名称 | NoteBuddy 软件工程详细设计说明书 |
| 文档版本 | v1.0 |
| 对应概要设计 | 《NoteBuddy 概要设计说明书》 |
| 代码基线 | `feat/agent-edit`（包含 `2964604`） |
| 更新日期 | 2026-11-10 |

## 1 系统概述

### 1.1 系统简介

NoteBuddy 是本地运行的课程学习工作区，把资料导入、结构化解析、笔记生成、正文编辑、知识导航与证据答疑放在同一套进程组内完成。系统以课程组织 Notebook，每个 Notebook 持有一份唯一可编辑正文；用户上传的课件经解析产生结构化文档表示（DocumentIR），正文块与原文块通过来源映射关联，覆盖检查、引用显示与关系分析均以该映射为依据。

系统由浏览器界面、FastAPI 服务、独立 Worker 与本地 SQLite 四部分组成，浏览器不直接访问数据库与文件系统。耗时操作以持久任务形式登记，由 Worker 领取执行，前端通过任务接口获取进度。详细设计在概要设计确定的八个模块边界内，说明各模块的输入数据、输出数据、数据结构、算法流程与函数接口，作为编码与测试的依据。

### 1.2 术语表

| 术语 | 定义 |
|---|---|
| Notebook | 笔记容器，持有 `document_json` 正文、`document_revision` 版本号与课程归属；一门课程可有多本，也可暂时未绑定课程 |
| 正文（document） | 以 ProseMirror JSON 表达的文档树，节点带稳定 `blockId`，是唯一可编辑内容 |
| Asset | 文件身份记录，保存 `storage_key`、`sha256`、字节数与处理路线；同一文件可被多个 Notebook 通过归属表引用 |
| Material | 课件业务记录，绑定 Asset、讲次标题与章节序号，承载解析状态与页数 |
| DocumentIR | 解析结果的结构化中间表示，由页、块、小节与质量报告组成 |
| ParseRun | 一次解析运行，同一 Asset 可有多条，其中至多一条 `is_current` |
| 页 / 块 | 页是课件中的可定位单位，块是页内的文本、表格、公式或图片单元 |
| Section | 由正文派生的章节索引，供目录、搜索与跳转使用 |
| 来源映射 | 正文块到解析运行与原文块的对应记录，附带正文指纹与状态 |
| 指纹（fingerprint） | 内容规范化后的 SHA-256 摘要，用于判断正文块、候选片段或解析版本是否同一 |
| CAS | 比较并交换，写入时以 `document_revision` 为条件更新，影响行数不为 1 即判为冲突 |
| SSE | Server-Sent Events，用于答疑与任务进度的流式推送 |
| Worker | 独立进程，凭任务表与操作系统文件锁领取并执行持久任务 |
| 预算 | 以单个 Asset 为单位的费用闸门，含限额、预留与结算三态 |
| 抑制记录 | 用户否决过的关系组合，后续分析跳过该组合 |

### 1.3 系统运行环境

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11，单机单用户 |
| 运行时 | Python 3.12 及以上；Node.js 22.22.2 及以上 |
| 服务端口 | Web 5173，API 8000，均绑定 `127.0.0.1` |
| 数据库 | SQLite 单文件 `data/notebook.sqlite3`，由 SQLAlchemy 2.0 访问 |
| 浏览器 | 现代桌面浏览器；不提供移动端布局 |
| 外部服务 | 文本模型、视觉模型、Embedding、联网搜索，均按配置启用；未配置时相关能力不可用，本地浏览不受影响 |
| 数据目录 | 默认 `./data`，可由 `NOTEBOOK_DATA_DIR` 指定 |

数据目录结构如下：

| 目录 | 内容 |
|---|---|
| `data/notebook.sqlite3` | 业务数据库 |
| `data/originals/` | 原始课件，按 `<material_id><扩展名>` 命名 |
| `data/derived/` | 页渲染图、抽取图片与解析派生文件 |
| `data/notebooks/<id>/images/` | 正文内嵌图片 |
| `data/staging/` | 上传临时文件，落盘后原子改名 |
| `data/backups/` | 备份包与设置改写前的 `.env` 副本 |
| `data/logs/` | 运行与任务日志 |
| `data/worker.lock` | Worker 单实例互斥锁 |

部署形态与进程关系见概要设计图 2。

### 1.4 开发环境

| 类别 | 工具与版本 |
|---|---|
| 前端框架 | React 19.1、TypeScript 5.9、Vite 7.1、React Router 7.18 |
| 富文本 | Tiptap 3.32（ProseMirror） |
| 后端框架 | FastAPI 0.115+、SQLAlchemy 2.0.36+、Alembic 1.20+ |
| 文档解析 | pypdf 6.19+、pypdfium2 5.14、python-docx 1.2+、Pillow 11+、python-pptx |
| 测试 | 后端 pytest + Ruff；前端 Vitest 5.0 + 生产构建检查 |
| 环境准备 | PowerShell 7、uv、Node 22.22.2，依赖安装到仓库内 `.runtime` 目录 |

后端包结构为 `ai`、`api`、`core`、`db`、`document_processing`、`forest`、`generation`、`knowledge`、`migration`、`notes`、`parsers`、`retrieval`、`schemas`、`services`、`web_search`、`workers`，共 208 个 Python 文件。

## 2 数据结构说明

### 2.1 常量

#### 2.1.1 运行配置常量

配置对象由 `app/core/config.py` 的 `Settings` 数据类定义，进程启动时读取环境变量并实例化单例 `settings`。

| 常量名 | 默认值 | 含义 |
|---|---|---|
| `NOTEBOOK_DATA_DIR` | `./data` | 数据根目录，相对路径按仓库根解析 |
| `NOTEBOOK_MAX_UPLOAD_MB` | 50 | 标准路线上传上限（字节数由 MB 换算） |
| `NOTEBOOK_MAX_PAGES` | 500 | 标准路线页数上限 |
| `NOTEBOOK_LLM_MAX_UPLOAD_MB` | 200 | 直读路线上传上限 |
| `NOTEBOOK_LLM_MAX_PAGES` | 2000 | 直读路线页数上限 |
| `NOTEBOOK_ALLOWED_EXTENSIONS` | `.pptx,.pdf,.docx` | 允许的扩展名集合 |
| `NOTEBOOK_GENERATOR` | `deepseek` | 正文生成器标识 |
| `NOTEBOOK_GENERATION_BATCH_CHARS` | 18000 | 单次生成批次的输入字符预算，下限 2000 |
| `NOTEBOOK_GENERATION_MAX_CHARS` | 120000 | 单份资料生成的总字符上限，下限 10000 |
| `NOTEBOOK_DOCUMENT_PROCESSING_ROUTE` | `standard` | 默认解析路线 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 模型服务地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 默认文本模型 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 60 | 模型请求超时 |
| `DEEPSEEK_INPUT_COST_PER_MILLION` | 0 | 输入侧单价（元/百万 token） |
| `DEEPSEEK_OUTPUT_COST_PER_MILLION` | 0 | 输出侧单价 |
| `WEB_SEARCH_TIMEOUT_SECONDS` | 20 | 联网检索超时 |
| `EMBEDDING_BASE_URL` / `MODEL` | 空 | 向量化服务，可选 |

`data_dir` 与 `allowed_extensions` 属于结构约束，不通过设置接口修改；其余字段可在写入 `.env` 后热更新，无需重启进程。

#### 2.1.2 业务常量

| 常量 | 值 | 所在文件 | 含义 |
|---|---|---|---|
| `BUDGET_LIMIT_FEN` | 1000 | `services/processing_budget.py` | 单 Asset 费用上限（分） |
| `FX_MAX_AGE_DAYS` | 30 | 同上 | 汇率有效期（天） |
| `FORMAT_VERSION` | 2 | `services/backup.py` | 备份包格式版本 |
| `MAX_FILES` | 2000 | 同上 | 备份包文件数上限 |
| `MAX_ARCHIVE_BYTES` | 2 GB | 同上 | 备份包解压后总大小上限 |
| `QUIZ_MAX_ITEMS` | 5 | `services/quiz.py` | 单次测验题量上限 |
| `QUIZ_GENERATION_RETRIES` | 2 | 同上 | 出题重试次数 |
| `QUIZ_SOURCE_MAX_CHARS` | 6000 | 同上 | 出题材料字符上限 |
| `SHORT_ANSWER_MAX_CHARS` | 500 | 同上 | 简答题作答长度上限 |
| `SKILL_RETRIES` | 2 | `services/skills.py` | 提纲与辨析的重试次数 |
| `SKILL_SOURCE_MAX_CHARS` | 9000 | 同上 | 技能类材料字符上限 |
| `OUTLINE_MAX_MODULES` | 8 | 同上 | 复习提纲模块上限 |
| `CONTRAST_MAX_PAIRS` | 4 | 同上 | 概念辨析对数上限 |
| `MAX_SOURCE_IMAGE_BYTES` | 20 MB | `services/image_assets.py` | 单张引用图片大小上限 |
| `MAX_SNAPSHOTS` | 100 | `notes/history.py` | 单笔记保留的修订快照上限 |
| `MAX_AGE_DAYS` | 90 | 同上 | 修订快照最长保留天数 |
| `MAX_TOOL_ROUNDS` | 6 | `ai/agent_loop.py` | 答疑工具调用轮次上限 |
| `TOOL_RESULT_MAX_CHARS` | 1600 | `ai/agent_read_tools.py` | 单条工具结果回填字符上限 |
| `BATCH_IDLE_CLOSE` | 2 分钟 | `services/notebook_generation_inputs.py` | 上传批次空闲关闭阈值 |
| `PROMPT_VERSION` | `notebook-generation-v4-math-contract` | `workers/notebook_generation_worker.py` | 生成提示词版本，写入任务记录 |
| `ATTACHMENT_CLEANUP_INTERVAL` | 3600 秒 | `workers/runner.py` | 附件清理周期 |
| `FOREST_CHECK_INTERVAL` | 3 轮 | 同上 | 每 N 轮处理一次森林任务 |
| `GENERATION_COORDINATION_INTERVAL` | 1.0 秒 | 同上 | 生成输入协调间隔 |

#### 2.1.3 正文校验常量

定义在 `app/notes/document.py`，超限即抛出 `DocumentValidationError`。

| 常量 | 值 | 校验对象 |
|---|---|---|
| `MAX_NODES` | 8000 | 文档节点总数 |
| `MAX_DEPTH` | 12 | 节点嵌套深度 |
| `MAX_BLOCK_TEXT` | 20000 | 单个块字符数 |
| `MAX_TOTAL_TEXT` | 1000000 | 全文正文字符数 |
| `MAX_DOCUMENT_BYTES` | 8000000 | 序列化后字节数 |
| `MAX_BLOCK_ID` | 64 | 块标识长度 |
| `MAX_ATTACHMENT_ALT` | 300 | 图片替代文本长度 |
| `MAX_LATEX` | 2000 | 单个公式源码长度 |

#### 2.1.4 数据文件

| 文件 | 所在目录 | 格式 | 说明 |
|---|---|---|---|
| `notebook.sqlite3` | `data/` | SQLite | 全部业务表 |
| `<material_id>.pdf/.pptx/.docx` | `data/originals/` | 原格式 | 上传原件，只增不改 |
| `<run_id>/p<页号>.png` | `data/derived/` | PNG | 页渲染图，按需生成 |
| `<run_id>/fig-<块号>.<扩展名>` | `data/derived/` | PNG/JPEG | 抽取的图片与公式图 |
| `<attachment_id>.<扩展名>` | `data/notebooks/<id>/images/` | 图片 | 正文内嵌图片 |
| `upload-*.tmp` | `data/staging/` | 二进制 | 上传中间文件，成功后改名 |
| `backup-<时间戳>.zip` | `data/backups/` | ZIP | 备份包，含清单与数据库快照 |
| `.env.bak-<时间戳>` | `data/backups/` | 文本 | 设置改写前的环境文件副本 |
| `worker.lock` | `data/` | 空文件 | 操作系统文件锁载体 |

### 2.2 变量

| 变量 | 类型 | 作用域 | 说明 |
|---|---|---|---|
| `settings` | `Settings` | 进程级单例 | 全模块共享的配置对象；设置接口写入后原地更新字段 |
| `STOP` | `bool` | `workers/runner.py` 模块级 | 信号处理置位，控制 Worker 循环退出 |
| `_active_budget` | `ContextVar[BudgetContext \| None]` | 请求/任务上下文 | 当前生效的费用账本，供模型客户端读取 |
| `db` | `Session` | 单次请求或单次任务 | 由依赖注入创建，事务边界在路由或 Worker |
| `notebook.document_revision` | `int` | 持久化字段 | 正文版本，CAS 条件与快照依据 |
| `notebook.order_revision` | `int` | 持久化字段 | 章节排序版本，与正文版本分开维护 |
| `job.input_snapshot_json` | `str` | 任务记录 | 生成输入冻结快照，重试时据此复现 |
| `plan` | `dict` | 生成流程局部 | 知识单元计划，落库到 `knowledge_plan_json` |

`settings` 不可整体替换：`_apply_to_process` 只逐字段赋值，避免已持有引用的模块读到旧对象。

### 2.3 数据结构

#### 2.3.1 DocumentIR 文档树

定义于 `app/document_processing/ir.py`，是解析与生成之间的交换格式。

`DocumentIR` 顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `document_id` | str | 文档标识 |
| `asset_id` | str | 来源资产 |
| `parse_run_id` | str | 产生该 IR 的解析运行 |
| `doc_type` | str | `pdf` / `pptx` / `docx` / `unknown` |
| `file_sha256` | str \| None | 源文件摘要，用于验证 IR 与文件对应 |
| `parser_name` / `parser_version` | str | 解析器标识与版本 |
| `config_version` | str | 解析配置版本 |
| `page_count` | int | 页数 |
| `pages` | list[PageIR] | 页列表，按页号有序 |
| `sections` | list[SectionIR] | 小节列表 |
| `quality` | QualityReport | 质量报告 |
| `warnings` | list[str] | 文档级告警 |
| `ir_version` | int | IR 结构版本 |
| `fingerprint` | str | 规范化 JSON 的 SHA-256 |

`PageIR` 字段：`page_id`、`page_number`、`width`、`height`、`rotation`、`render_key`、`extraction`（`native_text` / `ocr` / `vision`）、`status`（`parsed` / `failed`）、`text`、`confidence`、`warnings`、`blocks`。

`BlockIR` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `block_id` | str | 块标识，在一次解析运行内唯一 |
| `page_number` | int | 所属页 |
| `order` | int | 页内顺序 |
| `global_order` | int | 全文顺序，用于跨页定位 |
| `type` | str | `title` / `paragraph` / `list` / `table` / `figure` / `formula` / `code` |
| `level` | int | 标题层级，0 表示非标题 |
| `text` | str | 文本内容 |
| `latex` | str \| None | 公式源码 |
| `table` | TableData \| None | 表格行列与合并信息 |
| `figure` | FigureData \| None | 图片键、尺寸与题注 |
| `bbox` | list[float] \| None | 版面坐标 `[x0, y0, x1, y1]` |
| `source` | SourceSpan \| None | 原始位置跨度 |
| `extraction` | str | 提取方式 |
| `confidence` | float \| None | 置信度 |
| `warnings` | list[str] | 块级告警 |
| `parent_id` | str \| None | 父块，用于列表嵌套 |

`SectionIR` 字段：`section_id`、`order`、`title`、`level`（0–6）、`page_start`、`page_end`、`block_ids`。

`QualityReport` 字段：`status`、`score`、`pages_total`、`pages_ok`、`pages_empty`、`pages_failed`、`text_chars`、`text_chars_per_page`、`issues`、`usable_page_ranges`、`generation_allowed`、`generation_block_reason`。`status` 取值为 `complete`、`partial`、`needs_ocr`、`needs_vision`、`failed`；`generation_allowed` 由可用页范围、是否存在 blocking 级问题与状态共同决定。`QualityIssue` 含 `code`、`severity`（`blocking` / `warning` / `info`）、`message`、`page_numbers`、`retry_hint`。

`DocumentIR` 提供 `all_blocks()`、`block_by_id()`、`block_text()`、`plain_text()`、`validate()`、`canonical_json()`、`compute_fingerprint()`、`seal()`。`seal()` 先校验再写入指纹，指纹不参与自身计算。

#### 2.3.2 正文文档结构

`document_json` 为 ProseMirror 风格对象：

```
{
  "type": "doc",
  "content": [
    {"type": "heading", "attrs": {"level": 2, "blockId": "blk_xxx"}, "content": [{"type": "text", "text": "..."}]}
  ]
}
```

顶层节点类型限定为 `paragraph`、`heading`、`bulletList`、`orderedList`、`taskList`、`blockquote`、`codeBlock`、`horizontalRule`、`table`、`callout`、`example`、`image`、`blockMath`；容器与行内类型为 `doc`、`text`、`hardBreak`、`listItem`、`taskItem`、`tableRow`、`tableCell`、`tableHeader`、`inlineMath`。顶层节点必须带 `blockId`，`text` 节点可带 `marks`（`bold`、`italic`、`underline`、`strike`、`link`、`code`、`highlight`），属性键按节点类型白名单校验。

校验规则由 `validate_document` 执行：字段白名单校验、节点类型白名单、深度与数量上限、`blockId` 唯一且长度受限、图片 `assetId` 必填、公式源码长度受限。校验失败抛 `DocumentValidationError`。

#### 2.3.3 生成快照与计划

`build_snapshot(db, notebook, asset_ids)` 产出任务输入快照：

| 字段 | 说明 |
|---|---|
| `notebook_id` / `notebook_title` | 目标笔记 |
| `base_document_revision` | 规划时刻的正文版本 |
| `current_document` | 当前正文全文，用于去重与合并 |
| `current_outline` | 当前正文的标题树 |
| `sources` | 每份资料的 `asset_id`、解析运行、IR 指纹、页码、质量状态、块清单与处理路线 |
| `generator` / `processing_route` / `provider` | 生成器、解析路线与模型配置快照 |
| `batch_chars` | 单批字符预算 |
| `created_for_assets` | 本次输入的资产清单 |

同一任务只允许一条处理路线的资料；混用 `standard` 与 `llm` 时构造快照直接拒绝。

计划由 `build_plan(snapshot)` 生成，每个 `KnowledgeUnit` 含 `unit_id`、`title`、`block_ids`、`chars`、`output_tokens`、`action`（`new` / `extend` / `skip`）、`order`。计划写入 `notebook_generation_jobs.knowledge_plan_json`。

#### 2.3.4 任务与状态取值

| 表 | 状态字段取值 |
|---|---|
| `processing_jobs` | `pending`、`processing`、`completed`、`failed`、`cancelled` |
| `notebook_generation_jobs` | `pending`、`processing`、`completed`、`failed`、`cancelled`、`cancel_requested` |
| `notebook_generation_inputs` | `open`、`waiting_parse`、`parsing`、`parse_failed`、`ready`、`generating`、`completed`、`partial_failure` |
| `notebook_generation_candidates` | `pending_review`（默认值） |
| `asset_processing_jobs` | `pending`、`waiting_parse`、`processing`、`parse_failed`、`completed`、`completed_with_warnings`、`failed` |
| `document_parse_runs` | `pending`、`running`、`completed`、`failed` |
| `forest_jobs` | `pending`、`processing`、`completed`、`failed` |
| `backup_records` | `processing`、`completed`、`failed`、`validated_to_isolated_directory` |

`processing_jobs.phase` 记录阶段名，取值为 `parse`、`ai_read`、`completed`、`failed`。

#### 2.3.5 统一错误响应

接口层把所有预期失败映射为统一结构：

```
{"detail": "可读原因"}
```

`ApplicationError` 携带 `status_code` 与 `detail`；`UploadRejected`、`AttachmentRejected` 等继承 `ValueError` 并自带状态码，由路由的异常处理转换为上述结构。响应不包含堆栈、SQL 与内部路径。
## 3 模块设计

### 3.1 软件结构

系统在概要设计确定的八个模块内实现，模块与代码位置对应如下：

| 编号 | 模块 | 主要代码位置 | 职责 |
|---|---|---|---|
| M1 | 课程与笔记本 | `api/v1/courses.py`、`services/notebook_lifecycle.py`、`notes/notebook.py` | 课程增删改查、Notebook 生命周期、目录投影 |
| M2 | 资料接入与解析 | `services/uploads.py`、`document_processing/`、`parsers/`、`workers/material_worker.py` | 上传受理、容器校验、解析运行、质量评估、分块 |
| M3 | 笔记生成 | `generation/`、`services/generation_jobs.py`、`workers/notebook_generation_worker.py` | 输入快照、知识单元规划、正文合成、质量门禁、来源写入 |
| M4 | 正文编辑与版本 | `notes/`、`services/notebook_document.py` | 正文校验、CAS 写入、修订快照、目录重建、来源失效 |
| M5 | 知识森林与关系 | `forest/`、`knowledge/` | 课程树、跨笔记本关系、培养方案导入、知识点提议 |
| M6 | 智能答疑与学习工具 | `ai/`、`services/conversations.py`、`services/quiz.py`、`services/skills.py` | 定域问答、工具调用、证据核验、测验与复习产物 |
| M7 | 配置与运行 | `core/config.py`、`core/settings_store.py`、`services/processing_budget.py`、`workers/runner.py` | 配置读写、能力预检、费用预算、任务调度 |
| M8 | 备份恢复 | `services/backup.py`、`api/v1/backup.py` | 备份导出、校验预览、隔离恢复 |

模块间调用关系：

| 调用方 | 被调方 | 契约 |
|---|---|---|
| M1 | M4 | 新建 Notebook 时写入空文档 `empty_document()` |
| M2 | M3 | 解析完成写入 `AssetParseResult`，生成任务按资产读取 |
| M3 | M4 | 经 `write_document` 追加正文，携带 `base_document_revision` |
| M3 | M5 | 正文变化后 `enqueue_notebook_relations` 登记关系分析 |
| M4 | M5 | 保存成功后按 `refresh_relations` 触发候选重算 |
| M6 | M2/M3/M4 | 只读工具读取正文、页、覆盖与解析结果 |
| M7 | 全部 | 提供 `settings`、费用闸门、任务领取与锁 |
| M8 | 全部 | 只读数据库快照与资产目录 |

调用方向为单向：路由调用服务，服务调用模型与文件系统，Worker 与服务共用同一套服务函数，不另建写入路径。跨模块不传递 ORM 实体，只传标识、字典快照与值对象。

### 3.2 功能设计说明

详细设计遵循五条原则，每条都对应可检查的实现约束。

**一、正文唯一入口。** 所有正文写入必须经过 `notes/store.py` 的 `write_document`。该函数完成校验、CAS 更新、快照、目录重建与来源失效五件事，任何绕过它的写入都会使派生的章节与来源映射失真。参数 `origin` 区分 `autosave`、`restore`、`generation` 三种来源，写入修订表供追溯。

**二、来源与正文分离。** `DocumentIR` 只描述原文件，不参与正文；正文块与原文块通过 `notebook_block_sources` 关联，并冗余保存正文指纹。指纹不一致即视为来源已失效，稳定块标识本身不能证明内容仍受原始资料支持。

**三、先规划后生成。** 规划阶段完全由确定性代码完成，输出知识单元清单与动作（新增、扩展、跳过），计划先落库再调用模型。这样"是否重复"由代码判定，模型只负责在既定单元内组织语言。

**四、门禁先于落地。** 模型输出依次通过结构校验、公式检查、来源映射校验、图片拒绝四道门禁；答疑的回答先经过证据核验再发布正文。任一门禁失败，保留既有内容并把任务置为失败，不写入半成品。

**五、任务可重放。** 上传与生成都登记持久任务，输入以快照冻结；模型步骤结果写入 `processing_steps`，重试时按指纹复用。任务状态推进只由持有文件锁的 Worker 执行，避免并发重复处理。

### 3.3 课程与笔记本模块

#### 3.3.1 设计图

```
浏览器工作区
   │  /courses、/courses/{id}/notebooks、/notebooks/unbound
   ▼
api/v1/courses.py
   │  参数与归属校验
   ▼
services/notebook_lifecycle.py ──┬──> notes/notebook.py（目录投影、默认笔记）
   │                             └──> services/deletion.py（预览、软删、检查点）
   ▼
db/models.py：courses、notebooks
```

#### 3.3.2 功能描述

课程维度提供新建、列表（按最近打开排序）、修改、进入记录、总览统计、删除预览与软删除、回收站查询与恢复。Notebook 维度提供创建（挂课程或未分类）、重命名、绑定与解绑、移动、排序、软删除、恢复、永久删除与批量操作。绑定只改归属，不动正文；解绑后 Notebook 进入未分类列表，正文与资料保持可用。

#### 3.3.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| 课程名称 | 表单 | 去首尾空白后非空，长度不超过 200 |
| 课程说明 | 表单 | 可空，长文本 |
| Notebook 标题 | 表单 | 非空，长度不超过 200 |
| `course_id` | 路径或表单 | 课程存在且 `deleted_at` 为空 |
| `notebook_ids` | 批量操作 | 非空数组，逐项校验归属，重复项去重 |
| `expected_order_revision` | 排序请求 | 必须等于当前 `notebooks.order_revision`，否则冲突 |
| `action` | 批量操作 | 限定为 `delete`、`restore`、`move`、`bind` |

数据取自 `courses`（名称、删除状态、排序版本）、`notebooks`（归属、顺序、删除状态）、`materials` 与 `conversations`（统计与级联范围）。删除前的任务检查读取 `processing_jobs`、`asset_processing_jobs`、`notebook_generation_jobs` 中未完成的记录。

#### 3.3.4 输出数据

| 输出 | 结构 | 表现形式 |
|---|---|---|
| 课程对象 | `id`、`name`、`description`、`notebook_count`、`material_count`、`last_opened_at` | JSON |
| Notebook 对象 | `id`、`title`、`course_id`、`display_order`、`document_revision`、`is_default`、`deleted_at` | JSON |
| 课程总览 | 资料数、笔记数、知识点数、最近活动时间 | JSON |
| 删除预览 | `materials`、`pages`、`source_refs`、`document_blocks`、`original_bytes`、`active_jobs`、`action` | JSON |
| 删除结果 | 受影响对象计数与检查点路径 | JSON |
| 批量结果 | 成功项、跳过项、失败项及原因 | JSON |

#### 3.3.5 数据设计

`courses` 表：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | VARCHAR(36) | 主键 | UUID |
| `name` | VARCHAR(200) | 非空 | 课程名 |
| `description` | TEXT | 可空 | 说明 |
| `created_at` | DATETIME | 非空 | 创建时间（UTC） |
| `deleted_at` | DATETIME | 可空 | 软删除标记 |
| `notebook_order_revision` | INTEGER | 非空，默认 0 | 排序版本 |
| `last_opened_at` | DATETIME | 可空 | 最近进入时间 |

`notebooks` 表：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | VARCHAR(36) | 主键 | UUID |
| `course_id` | VARCHAR(36) | 外键，可空 | 空表示未分类 |
| `title` | VARCHAR(200) | 非空 | 标题 |
| `display_order` | INTEGER | 非空 | 课程内显示顺序 |
| `order_revision` | INTEGER | 非空 | 排序版本，与正文版本分开 |
| `document_json` | TEXT | 非空 | 正文 |
| `document_revision` | INTEGER | 非空 | 正文版本 |
| `is_default` | BOOLEAN | 非空 | 课程默认笔记本 |
| `tree_slot` | INTEGER | 非空 | 课程内槽位 |
| `cover_filename` / `cover_mime` | VARCHAR | 可空 | 封面 |
| `deleted_at` | DATETIME | 可空 | 软删除 |

唯一约束：`uq_notebooks_course_slot`（课程内槽位唯一）、部分唯一索引 `uq_notebooks_default`（`is_default = 1` 时课程内唯一）。

#### 3.3.6 算法和流程

删除课程：

1. `ensure_notebook_has_no_active_jobs` 检查所属 Notebook 是否存在未完成任务，有则拒绝。
2. `impact_preview` 统计受影响的资料、页、来源引用、块与原文件字节。
3. `_checkpoint()` 调用 SQLite 备份接口，在 `data/backups/` 生成检查点。
4. `soft_delete_course` 置 `deleted_at`，同时软删其 Notebook 与资料。
5. 返回删除结果与检查点路径。

绑定 Notebook 到课程：

1. `_active_course` 读取课程并确认未删除。
2. 若课程内已有默认笔记本且本次绑定不继承默认，调用 `_ensure_course_default` 保持默认项唯一。
3. 写入 `course_id` 与 `tree_slot`，调用 `bump_order_revision` 递增排序版本。
4. 提交后触发 `enqueue_notebook_relations` 登记关系分析。

排序采用乐观并发：请求携带 `expected_order_revision`，`reorder_notebook_outline` 以该值作为更新条件，影响行数为 0 时返回 409，不覆盖他人排序。

#### 3.3.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `list_unbound_notebooks(db)` | `services/notebook_lifecycle.py` | 列出未分类 Notebook | 返回 `list[Notebook]` |
| `create_unbound_notebook(db, title)` | 同上 | 新建未分类 Notebook | 返回 `Notebook`，正文取列默认值 |
| `bind_notebook(db, notebook_id, course_id)` | 同上 | 绑定到课程 | 校验课程有效，返回 `Notebook` |
| `unbind_notebook(db, notebook_id)` | 同上 | 解除归属 | 保留正文与资料，返回 `Notebook` |
| `move_notebook(db, notebook_id, course_id)` | 同上 | 跨课程移动 | 同时调整槽位与默认项 |
| `bulk_manage_notebooks(db, notebook_ids, action, course_id)` | 同上 | 批量删除/恢复/移动 | 返回 `{succeeded, skipped, failed}` |
| `delete_course_notebook(db, course_id, notebook_id)` | 同上 | 课程内软删除 | 先检查活动任务 |
| `restore_deleted_notebook(db, notebook_id, course_id)` | 同上 | 从回收站恢复 | 冲突槽位时重新分配 |
| `permanently_delete_notebook_service(db, notebook_id)` | 同上 | 永久删除 | 仅允许已软删除对象 |
| `get_notebook_outline(db, course_id, notebook_id)` | 同上 | 目录投影 | 返回章节树与排序版本 |
| `reorder_notebook_outline(db, course_id, notebook_id, material_ids, expected_order_revision)` | 同上 | 重排章节 | 版本不符抛冲突 |
| `impact_preview(db, course_id, material_id)` | `services/deletion.py` | 删除影响统计 | 返回计数与字节数 |
| `soft_delete_course(db, course)` | 同上 | 课程软删除 | 级联软删 Notebook 与资料 |

使用约束：本模块函数不直接写 `document_json`；新建 Notebook 只能写入 `empty_document()`，后续修改一律经正文模块。

#### 3.3.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `settings.data_dir` | 读 | 删除前检查点写入 `backups` 子目录 |
| `courses.notebook_order_revision` | 读写 | 课程内排序版本，递增即失效旧请求 |
| `notebooks.order_revision` | 读写 | 章节排序版本 |
| `notebooks.document_revision` | 只读 | 仅用于展示与后续写入的基准，不在本模块修改 |
| `notebooks.document_json` | 不写 | 新建时不赋值，由列默认值提供 |

### 3.4 资料接入与解析模块

#### 3.4.1 设计图

```
POST /notebooks/{id}/assets（multipart）
      │
      ├─ 路线解析 resolve_route ── llm 时 ensure_vision_preflight
      ├─ 扩展名白名单 + 大小上限
      ├─ staging 流式写入（1 MB 分块）+ SHA-256
      ├─ 容器校验（PDF 签名与页数 / ZIP 结构）
      ├─ 幂等键查询 → 内容哈希查重 → 取写锁后复查
      ├─ originals 原子改名 + fsync 目录
      └─ assets / materials / processing_jobs(pending)
                     │
        Worker：claim_next_job → process_material
                     │
   create_parse_run → execute_parse_run → 质量评估 assess
                     │
   document_pages / document_blocks / document_chunks
```

#### 3.4.2 功能描述

接收 Notebook 资料与图片，登记资产与上传批次，校验文件真实格式后原子落盘，并登记解析任务。解析按"运行"组织：每次解析创建一条 `document_parse_runs`，逐页提取文本、标题层级、表格、公式与图片，产出 `DocumentIR`；无法提取文字的页转 OCR，仍失败则记录失败状态与告警。解析完成后评估质量、切分检索块、生成页渲染图，并把该运行提升为当前版本。

#### 3.4.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| 文件流 | multipart | 扩展名在 `allowed_extensions` 内；大小不超过路线限额；空文件拒绝 |
| `lecture_title` | 表单 | 为空时取文件名（去扩展名） |
| `topic_title` | 表单 | 可空 |
| `processing_route` | 表单 | `standard` 或 `llm`；`llm` 需视觉配置通过预检 |
| `Idempotency-Key` | 请求头 | 与 `notebook_id`、路线一起散列，同键返回原任务 |
| `allow_duplicate` | 表单 | 为真时允许哈希相同的文件作为新讲次 |
| `upload_batch_id` | 表单 | 批次存在且属于同一 Notebook |

容器校验规则：PDF 读取前 5 字节须为 `%PDF-`，页数不超过路线限额；PPTX 与 DOCX 校验 ZIP 结构与必需条目。数据取自 `notebooks`、`courses`（归属）、`materials`（内容哈希查重）、`processing_jobs`（幂等键）。

#### 3.4.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 受理结果 | `material` 对象 + `job_id` + `status=pending` | HTTP 202 |
| 解析结果 | `DocumentIR`（页、块、小节、质量） | 持久化为 `document_parse_runs` 及子表 |
| 质量报告 | `status`、`issues`、`usable_page_ranges` | 决定是否允许生成 |
| 检索块 | 文本、页码列表、块标识列表、向量 | 写入 `document_chunks` |
| 页渲染 | PNG 路径 | 存放在 `data/derived/` |
| 任务进度 | `status`、`phase`、`completed_pages`、`total_pages`、`error_code` | 供任务接口查询 |

#### 3.4.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `assets` | `id`、`storage_key`（唯一）、`original_name`、`byte_size`、`sha256`、`extension`、`mime_type`、`state`、`processing_route`、`processing_config_json` | 文件身份 |
| `materials` | `id`、`notebook_id`、`course_id`、`asset_id`（唯一）、`lecture_title`、`chapter_order`、`status`、`page_count`、`content_hash`、`parser_version`、`deleted_at` | 课件业务记录 |
| `notebook_assets` | `notebook_id`、`asset_id`、`role`、`is_owner`、`detached_at` | 归属，部分唯一索引保证活动归属唯一 |
| `notebook_upload_batches` | `id`、`notebook_id`、`created_at`、`closed_at`、`processing_route` | 批次 |
| `document_parse_runs` | `id`、`asset_id`、`status`、`parser_name`、`parser_version`、`config_version`、`is_current`、`fingerprint`、`page_count`、`text_chars`、`quality_status`、`quality_json`、`supersedes_id` | 解析版本 |
| `document_pages` | `parse_run_id`、`page_number`、`logical_page_id`、`width`、`height`、`render_key`、`extraction`、`status`、`text`、`confidence`、`warnings_json` | 页 |
| `document_blocks` | `parse_run_id`、`page_id`、`block_id`、`parent_block_id`、`order`、`global_order`、`block_type`、`level`、`text`、`latex`、`table_json`、`figure_json`、`bbox_json` | 块 |
| `document_chunks` | `parse_run_id`、`asset_id`、`section_id`、`order`、`text`、`page_numbers_json`、`block_ids_json`、`embedding_json` | 检索块 |
| `processing_jobs` | `id`、`material_id`、`kind`、`status`、`phase`、`progress`、`completed_pages`、`total_pages`、`attempt_count`、`idempotency_key`、`heartbeat_at` | 任务 |
| `processing_steps` | `scope`、`stage`、`step_key`、`fingerprint`、`result_json`、`usage_json` | 模型步骤检查点 |

文件存储：原始文件按 `<material_id><扩展名>` 存放在 `originals`，数据库只存 `storage_key`；临时文件在 `staging`，通过 `os.replace` 原子改名，随后 `fsync` 父目录，保证不出现半截文件。

#### 3.4.6 算法和流程

落盘算法：

1. 在 `staging` 创建临时文件，按 1 MB 分块读取请求体，累计字节数并同步更新 SHA-256，超过路线限额立即中断并删除临时文件。
2. 写入完成后 `flush` 并 `fsync` 文件描述符。
3. 调用 `_validate_container` 按扩展名做真实格式校验。
4. 执行一次写操作以取得 SQLite 写锁，重新查询幂等键与内容哈希，避免并发重复提交。
5. 生成 `material_id`，调用 `bump_order_revision` 串行分配 `chapter_order`。
6. 把临时文件 `os.replace` 到 `originals`，再 `fsync` 目录，最后写 `assets`、`materials`、`processing_jobs` 并提交。

解析流程：

1. `create_parse_run` 先查当前运行：已存在完成且解析配置兼容的运行则直接复用；否则新建 `pending` 运行，`supersedes_id` 指向旧运行，旧运行在新运行完成前保持当前状态。
2. `execute_parse_run` 按 `doc_type` 选择解析器，逐页产出 `PageIR` 与 `BlockIR`，每页回调 `progress` 更新已处理页数。
3. 无文字层的页调用 OCR；OCR 不可用或失败时把页状态置为 `failed` 并写入告警，不用空文本冒充成功。
4. `assess` 汇总质量：按页面覆盖率、结构完整度、置信度加权算分，输出 `complete`、`partial`、`needs_ocr`、`needs_vision` 或 `failed`，并给出 `generation_allowed`。
5. `generation_allowed` 为真时调用 `build_chunks` 切块（默认单块上限 1200 字、下限 40 字，超长按段落边界拆分）。
6. `_replace_children` 幂等写入页与块，`_promote_current` 把该运行置为当前版本。
7. 失败路径调用 `fail_parse_run` 写入错误码与信息，保留此前可用运行。

#### 3.4.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `ingest_document(db, *, course_id, source, filename, lecture_title, topic_title, media_type, allow_duplicate, idempotency_key, notebook_id, upload_batch_id, processing_route)` | `services/uploads.py` | 上传受理与落盘 | 返回 `(Material, ProcessingJob)`；失败抛 `UploadRejected` |
| `_validate_container(path, extension, *, processing_route)` | 同上 | 真实格式校验 | PDF 签名与页数、ZIP 结构 |
| `validate_upload_container(path, extension)` | 同上 | 非资料类上传的公开校验入口 | 无返回值，失败抛异常 |
| `reconcile_staged_document_assets(db, *, limit)` | 同上 | 修复落盘与入库之间的中断 | 返回处理条数 |
| `create_parse_run(db, *, asset, config, reparse)` | `document_processing/service.py` | 创建解析运行 | 返回 `DocumentParseRun` |
| `execute_parse_run(db, run_id, *, source_path, title, ocr_available, vision_available, progress, max_new_pages)` | 同上 | 执行解析 | 返回 `ParseOutcome` |
| `persist_existing_ir(db, *, asset, document, config)` | 同上 | 持久化历史 IR | 返回 `ParseOutcome` |
| `load_ir(db, run)` | 同上 | 从库重建 IR | 返回 `DocumentIR` |
| `current_run(db, asset_id, *, completed_only)` | 同上 | 取当前运行 | 返回 `DocumentParseRun \| None` |
| `fail_parse_run(db, run_id, *, code, message)` | 同上 | 标记失败 | 写入错误码与时间 |
| `rebuild_views(db, run_id)` | 同上 | 重建 markdown 与分块 | 不动页块证据 |
| `page_render(db, run, page_number)` | 同上 | 取或生成页图 | 返回 `Path \| None` |
| `resolve_route(value)` / `route_limits(route)` | `document_processing/config.py` | 路线与限额 | 返回路线名或 `(字节上限, 页上限)` |
| `assess(document, *, engines, doc_type, notes)` | `document_processing/quality.py` | 质量评估 | 返回 `QualityReport` |
| `build_chunks(document, *, max_chars, min_chars)` | `document_processing/chunking.py` | 切检索块 | 返回 `list[ChunkDraft]` |
| `get_step(db, scope, stage, key, identity)` / `put_step(...)` | `document_processing/checkpoints.py` | 步骤结果存取 | 命中返回结果，未命中返回空 |
| `process_material(job_id)` | `workers/material_worker.py` | 任务执行入口 | 无返回值，异常转任务失败 |

使用约束：`execute_parse_run` 只写自己的运行，不改其他运行的页块；`_promote_current` 必须在该运行全部子表写完后调用。

#### 3.4.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `settings.allowed_extensions` | 读 | 上传白名单 |
| `settings.max_upload_bytes` / `max_pages` | 读 | 标准路线限额 |
| `settings.llm_max_upload_bytes` / `llm_max_pages` | 读 | 直读路线限额 |
| `settings.data_dir` 及其子目录 | 读写 | 落盘、派生文件、暂存 |
| `DocumentIR` | 写（生成）、读（生成模块消费） | 解析产物 |
| `processing_steps` | 读写 | 模型步骤复用 |
| `FileProcessingBudget` | 写 | 付费解析的预留与结算 |

### 3.5 笔记生成模块

#### 3.5.1 设计图

```
POST /notebooks/{id}/generation-jobs {asset_ids, Idempotency-Key}
        │
        ├─ 归属与解析状态校验
        ├─ build_snapshot（冻结资料、页块、IR 指纹、当前目录）
        ├─ build_plan（知识单元：new / extend / skip）
        └─ notebook_generation_jobs(pending) + inputs
                        │
     Worker：claim_next_generation_job → process_generation_job
                        │
     compose（离线规则 / 模型分批） → 归一化 → 四道门禁
                        │
     write_document（CAS、base_document_revision） → notebook_block_sources
                        │
     enqueue_notebook_relations（关系候选）
```

#### 3.5.2 功能描述

把已完成的解析结果转成可阅读正文。生成前冻结输入并规划知识单元，标注新增、扩展与跳过；生成按批次调用模型，产出结构化节点而非自由文本；结果通过结构、公式、来源、图片四道校验后，以正文写入接口追加到对应讲次位置。任务支持重试、取消与幂等，重试复用已完成步骤。

#### 3.5.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| `asset_ids` | 请求体 | 可为空（取该 Notebook 全部就绪资料）；每项须属于该 Notebook 且解析完成 |
| `Idempotency-Key` | 请求头 | 与笔记标识、资产列表一起散列；同键且请求指纹一致时返回原任务 |
| `base_document_revision` | 任务创建时读取 | 写入任务；合并时作为 CAS 条件 |
| 正文当前内容 | `notebooks.document_json` | 规划阶段用于去重 |
| 解析结果 | `document_parse_runs`、`document_blocks` | 只消费 `completed` 且为当前版本的运行 |

数据取自 `notebooks`、`notebook_assets`（归属）、`document_parse_runs`（完成状态与质量）、`document_blocks`（块文本）、`materials`（讲次标题与顺序）。

#### 3.5.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 任务对象 | `id`、`status`、`phase`、`attempt_count`、`error_code` | 202 返回 |
| 知识计划 | `units[]`、`skipped[]`、`total_chars` | 写入 `knowledge_plan_json` |
| 正文增量 | ProseMirror 节点数组 | 追加到正文 |
| 来源映射 | 块标识 → 解析运行、原文块、页码 | 写入 `notebook_block_sources` |
| 候选结果 | 完整正文快照 | 写入 `notebook_generation_candidates` |
| 关系任务 | 关系候选任务标识 | 写入 `relation_job_id` |

#### 3.5.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `notebook_generation_jobs` | `id`、`notebook_id`、`idempotency_key`、`request_fingerprint`、`status`、`base_document_revision`、`input_snapshot_json`、`model`、`prompt_version`、`schema_version`、`attempt_count`、`error_code`、`parse_run_ids_json`、`ir_fingerprints_json`、`generator`、`knowledge_plan_json`、`source_map_json`、`relation_job_id` | 任务与输入冻结 |
| `notebook_generation_inputs` | `notebook_id`、`asset_id`、`batch_id`、`parse_kind`、`parse_job_id`、`generation_job_id`、`status`、`error_code`、`retry_count` | 逐资产消费状态 |
| `notebook_generation_candidates` | `job_id`、`notebook_id`、`document_json`、`status`、`expires_at` | 待审核结果 |
| `notebook_block_sources` | `notebook_id`、`block_id`、`generation_job_id`、`parse_run_id`、`document_block_id`、`page_number`、`confidence`、`body_fingerprint`、`status` | 来源映射 |
| `processing_steps` | `scope`、`stage`、`step_key`、`fingerprint`、`result_json` | 分批生成的步骤复用 |

`input_snapshot_json` 保存资料清单、每份资料的解析运行与 IR 指纹、页块摘要与当前目录，任务重试时据此复现输入，不受后续资料变更影响。

#### 3.5.6 算法和流程

1. `create_generation_job` 校验笔记归属与资产状态，计算 `request_fingerprint`，命中同键任务时直接返回。
2. `build_snapshot` 读取每份资料当前运行、IR 指纹与块清单，附当前正文目录与章节文本。
3. `build_plan` 按资料生成知识单元：标题级块聚合为单元，超长单元按块边界拆分；与既有目录比对后标注 `new`、`extend`、`skip`。
4. 计划落库，任务置 `pending`，等待 Worker 领取。
5. `process_generation_job` 按单元分批：单批输入不超过 `generation_batch_chars`，总输出不超过 `generation_max_chars`。
6. `compose` 生成节点：离线模式用规则模板组织标题、要点与表格；模型模式按单元组装上下文并要求返回 JSON。
7. 归一化：修复缺失块标识、把独立公式提升为公式节点、统一标题层级。
8. 四道门禁依次执行：结构校验（节点类型与层级）、公式检查（括号、环境、`left/right` 配对）、来源映射校验（每个块至少一个有效来源，且来源在图内）、图片拒绝（生成正文不含图片）。
9. 通过后调用 `write_document` 追加正文，`expected_revision` 取当前 `document_revision`；遇 `DocumentConflict` 时回滚本次追加、清理新生成的图片文件与来源项，重新读取最新正文后再合并，直到成功或达到重试上限，全程只追加不覆盖用户编辑。
10. `_write_sources` 写入来源映射，`_complete_inputs` 把逐资产输入置为完成，`enqueue_notebook_relations` 登记关系分析。

#### 3.5.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `create_generation_job(db, notebook_id, asset_ids, idempotency_key)` | `services/generation_jobs.py` | 创建任务 | 返回任务读取结构；重复请求返回原任务 |
| `retry_generation_job(db, notebook_id, job_id)` | 同上 | 重试 | 重置状态与尝试次数，保留快照 |
| `cancel_generation_job(db, notebook_id, job_id)` | 同上 | 取消 | 置 `cancelled`，不删既有正文 |
| `build_snapshot(db, notebook, asset_ids)` | `generation/context.py` | 冻结输入 | 返回快照字典；资产无效抛 `GenerationInputError` |
| `build_plan(snapshot)` | `generation/planner.py` | 知识单元规划 | 返回计划字典，含 `units` 与 `skipped` |
| `compose(snapshot, plan, unit_ids, *, generator)` | `generation/composer.py` | 合成正文节点 | 返回 `Composition` |
| `compose_offline` / `compose_deepseek` | 同上 | 两种生成器 | 返回 `Composition` |
| `combine_compositions(compositions)` | 同上 | 合并多批结果 | 保留各节点证据映射 |
| `repair_deepseek_document_format(nodes, source_map, allowed_source_ids, validation_error)` | 同上 | 格式返修 | 仅修格式，不新增事实 |
| `inspect_generated_math(document)` | `generation/quality_gate.py` | 公式门禁 | 返回 `MathQualityReport`，含失败码计数 |
| `planned_figures(snapshot, plan)` / `append_source_figures(...)` | `generation/figures.py` | 图表追加 | 只接受已持久化且归属有效的来源图 |
| `partition_payload_units(units)` / `split_payload_batch(units)` | `generation/budget.py` | 分批 | 按原块边界切分，保持顺序 |
| `claim_next_generation_job()` | `workers/notebook_generation_worker.py` | 领取任务 | 原子状态迁移，返回任务标识 |
| `process_generation_job(job_id)` | 同上 | 执行生成 | 无返回值，异常转失败态 |
| `_merge_with_retry(...)` | 同上 | 带重试合并 | 冲突时终止，不覆盖 |

使用约束：`compose` 不得写入数据库；所有持久化在 Worker 中完成。生成正文不包含图片节点，图片只能通过 `append_source_figures` 追加已存在来源的图。

#### 3.5.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `settings.generation_batch_chars` / `generation_max_chars` | 读 | 分批与总量控制 |
| `settings.notebook_generator` | 读 | 生成器选择 |
| `DocumentIR` | 只读 | 通过快照消费 |
| `notebooks.document_revision` | 读 | 作为 CAS 基准 |
| `notebooks.document_json` | 只读 | 规划去重依据 |
| `processing_steps` | 读写 | 分批结果复用 |
| `PROMPT_VERSION` | 写 | 记录到任务，便于区分结果版本 |

### 3.6 正文编辑与版本模块

#### 3.6.1 设计图

```
PUT /courses/{cid}/notebooks/{id}/document {content, expected_revision}
        │
        ├─ normalize_document（补齐 blockId）
        ├─ validate_document（白名单、上限、图片归属）
        ├─ UPDATE ... WHERE document_revision = expected_revision
        │         └─ rowcount != 1 → 409
        ├─ record_snapshot（写修订、裁剪旧版本）
        ├─ rebuild_notebook_sections（目录重建）
        ├─ mark_orphaned_sources_stale（来源失效/激活）
        └─ refresh_relations → enqueue_notebook_relations
```

#### 3.6.2 功能描述

提供正文读取、保存、历史查询与恢复。保存时做结构校验与版本比对，冲突直接拒绝；每次保存形成修订快照，可按版本查看与恢复；正文变化后重建章节索引、更新来源映射状态；记录阅读位置，支持回到上次位置。正文可导出为 Markdown，也可由 Markdown 导入为节点。

#### 3.6.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| `content` | 请求体 | 必须是 `{type: "doc", content: [...]}`；节点类型白名单；深度不超过 12；节点数不超过 8000 |
| `expected_revision` | 请求体或查询参数 | 必须等于当前版本，否则 409 |
| `origin` | 内部参数 | `autosave`、`restore`、`generation` |
| 图片 `assetId` | 节点属性 | 必须属于该 Notebook 且未被分离 |
| 恢复版本号 | 路径 | 该修订必须存在且属于当前 Notebook |

数据取自 `notebooks`（当前正文与版本）、`notebook_document_revisions`（历史）、`notebook_assets`（图片归属）。

#### 3.6.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 正文 | `{content, revision, updated_at}` | JSON |
| 保存结果 | 新版本号与规范化后的正文 | 冲突返回 409 |
| 章节列表 | `block_id`、标题、层级、所属讲次、页码锚点 | JSON |
| 块来源 | 该块关联的解析运行、原文块、页码、状态 | JSON |
| 修订列表 | 版本号、来源、时间 | 分页 |
| 恢复结果 | 新版本号 | 恢复形成新版本，不回退版本号 |

#### 3.6.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `notebooks` | `document_json`、`document_revision`、`updated_at` | 当前正文与版本 |
| `notebook_document_revisions` | `notebook_id`、`revision`、`schema_version`、`document_json`、`origin`、`retention`、`created_at` | 历史快照 |
| `notebook_sections` | `notebook_id`、`course_id`、`block_id`、`order`、`level`、`heading`、`text`、`revision` | 派生目录 |
| `notebook_block_sources` | `notebook_id`、`block_id`、`parse_run_id`、`document_block_id`、`page_number`、`body_fingerprint`、`status` | 来源与指纹 |
| `notebook_reading_positions` | `notebook_id`、`block_id`、`updated_at` | 阅读位置 |

约束：`uq_notebook_document_revisions`（Notebook 与版本唯一）、`uq_notebook_revision_id_notebook`（修订标识与 Notebook 组合唯一）。修订保留策略为最多 100 个快照、且不保留超过 90 天的快照，仅对 `retention = "rolling"` 的记录裁剪；被某次修订引用的图片资产在裁剪后仍可复用。

#### 3.6.6 算法和流程

保存算法（`write_document`）：

1. `normalize_document` 补齐缺失的 `blockId`，保证章节可定位。
2. `validate_document` 依次检查字段白名单、节点类型、深度、节点数、文本总量、字节数、图片归属与公式长度。
3. `load_document` 读取旧正文，比较规范化结果是否变化，得到 `body_changed`。
4. 执行条件更新：`WHERE id = ? AND document_revision = ? AND deleted_at IS NULL`，写入新正文与 `revision + 1`。
5. 影响行数不为 1 时抛 `DocumentConflict`，返回 409，不修改任何数据。
6. 调用 `record_snapshot` 写入修订快照并在同一事务内裁剪超限版本。
7. `rebuild_notebook_sections` 全量重建章节索引，写入当前版本号。
8. `mark_orphaned_sources_stale` 对正文已改写的块把来源置为 `stale`；对内容与历史完全一致的块重新激活原映射。
9. 需刷新关系且正文确有变化时，`enqueue_notebook_relations` 登记候选分析。

恢复算法：读取目标修订的正文，校验图片归属后可重新激活该修订固定的资产，再以当前版本作为 `expected_revision` 调用同一写入路径，形成新版本。历史版本本身不改动。

#### 3.6.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `validate_document(content)` | `notes/document.py` | 结构校验 | 返回规范化文档；失败抛 `DocumentValidationError` |
| `normalize_document(content)` | 同上 | 补齐 `blockId` | 返回文档 |
| `load_document(raw)` / `dump_document(content)` | 同上 | 序列化 | 返回 `StoredDocument` 或字符串 |
| `document_to_blocks(content)` | 同上 | 抽块文本 | 返回 `list[dict]` |
| `document_to_markdown(content)` | 同上 | 导出 Markdown | 未知节点降级为纯文本 |
| `markdown_to_nodes(text, *, block_id)` | 同上 | 导入 Markdown | 返回节点数组 |
| `write_document(db, notebook, content, *, expected_revision, origin, refresh_relations)` | `notes/store.py` | 统一写入 | 返回 `(新版本号, 文档)`；冲突抛 `DocumentConflict` |
| `mark_orphaned_sources_stale(db, notebook_id, content, *, previous_content)` | 同上 | 来源失效/激活 | 返回受影响条数 |
| `body_fingerprint(node)` | 同上 | 块内容指纹 | 返回 SHA-256 |
| `record_snapshot(db, notebook_id, revision, content, *, origin)` | `notes/history.py` | 写修订 | 返回修订记录 |
| `build_sections(content)` | `notes/index.py` | 生成章节草稿 | 返回 `list[SectionDraft]` |
| `rebuild_notebook_sections(db, notebook, content, revision)` | 同上 | 重建目录 | 返回章节数 |
| `search_sections(db, term, *, course_id, limit)` | 同上 | 目录搜索 | 返回章节列表 |
| `save_notebook_document(db, notebook, payload, *, refresh_relations)` | `services/notebook_document.py` | 保存入口 | 返回 `(版本号, 文档)` |
| `restore_notebook_document(db, notebook, source_revision, expected_revision, *, refresh_relations)` | 同上 | 恢复历史 | 形成新版本 |
| `get_block_sources(db, notebook_id, block_id)` | 同上 | 块来源查询 | 返回来源列表 |
| `validate_document_image_ownership(db, notebook_id, content)` | 同上 | 图片归属校验 | 失败抛异常 |
| `apply_edits(content, edits)` | `notes/edits.py` | 按建议批量改写 | 返回新文档；锚点无效抛 `EditRejected` |

使用约束：任何模块修改正文都必须调用 `write_document`；`document_revision` 只在该函数内递增，其他位置只读。

#### 3.6.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `notebooks.document_json` | 读写 | 唯一正文源 |
| `notebooks.document_revision` | 读写 | CAS 条件与快照依据 |
| `notebooks.order_revision` | 只读 | 章节排序，与本模块无关 |
| `notebook_sections` | 写 | 派生数据，可重建 |
| `notebook_block_sources` | 写 | 来源状态与指纹 |
| `settings` | 读 | 数据目录、附件目录 |
### 3.7 知识森林与关系模块

#### 3.7.1 设计图

```
正文保存 / 生成完成
        │
        ▼
enqueue_notebook_relations（按内容指纹去重）
        │
        ▼
forest_jobs(pending) ──> process_notebook_relation_job
        │
        ├─ candidate_snapshots（冻结候选片段）
        ├─ 模型判定 → RelationOutput（端点、类型、依据）
        ├─ 重查归属、端点与指纹
        └─ 有效结果写入 notebook_relations（origin=ai）
                    │
用户操作：接受 / 删除 ──> suppressions（删除决定受保护）
```

#### 3.7.2 功能描述

按课程浏览知识目录，定位到具体正文位置；维护 Notebook 之间的关系，支持人工建立、模型推断与用户否决；提供培养方案导入，解析为课程预览后由用户确认落库，并支持受保护撤销。课程树复用正文派生的章节索引，读取不调用模型。

#### 3.7.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| `course_id` | 路径 | 课程存在且未删除 |
| 关系端点 | 请求体 | 两个 Notebook 属于同一课程、互不相同、均未删除 |
| `relation_type` | 请求体 | 限定为 `related`、`prerequisite`、`application` |
| 关系锚点 | 请求体 | 可选块标识；写入时记录该块指纹 |
| 培养方案文件 | multipart | 扩展名与大小受限，按解析路线处理 |
| `expected_revision` | 请求体 | 课程概览或导入确认时使用 |

数据取自 `notebooks`（端点与正文）、`notebook_sections`（目录）、`document_blocks`（候选片段）、`notebook_relation_suppressions`（已否决组合）。

#### 3.7.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 课程树 | 课程 → Notebook → 章节层级 | JSON |
| 关系列表 | 端点标题、类型、说明、锚点位置、来源（人工/推断） | JSON |
| 候选任务 | 任务标识与状态 | 202 返回 |
| 培养方案预览 | 课程名称、学期、层级、先修要求、冲突项 | JSON |
| 知识点提议 | 提议标识、候选节点、置信度、依据 | JSON |

#### 3.7.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `forest_course_profiles` | `course_id`、`semester`、`level`、`learning_state`、`position`、`revision`、`prerequisites_json` | 课程树展示属性 |
| `notebook_relations` | `source_notebook_id`、`target_notebook_id`、`relation_type`、`description`、`source_block_id`、`target_block_id`、`source_fingerprint`、`target_fingerprint`、`origin` | 关系与锚点指纹 |
| `notebook_relation_suppressions` | 两端 Notebook、块标识、类型、创建时间 | 用户否决记录 |
| `cross_course_relations` | 课程间关系 | 跨课程连接 |
| `curriculum_imports` | `id`、`status`、`source_type`、`extracted_json`、`preview_json` | 培养方案导入 |
| `forest_jobs` | `id`、`kind`、`status`、`payload_json`、`attempt_count`、`error_code` | 森林任务 |
| `knowledge_nodes` | `id`、`course_id`、`name`、`summary`、`status` | 知识点 |
| `knowledge_edges` | `course_id`、`source_node_id`、`target_node_id`、`relation_type`、`confidence`、`created_by` | 知识点关系 |
| `knowledge_proposals` | `course_id`、`candidate_name`、`kind`、`confidence`、`rationale`、`status`、`proposed_delta` | 待审提议 |
| `knowledge_changes` | `proposal_id`、`change_type`、`before_json`、`after_json`、`reason` | 变更流水 |

约束：`uq_notebook_relations_endpoints_anchors` 对（源、目标、类型、源锚点、目标锚点）建唯一索引，锚点用 `coalesce(..., '')` 参与比较；`ix_notebook_relations_target` 支持反向查询。

#### 3.7.6 算法和流程

关系分析：

1. `candidate_snapshots` 按课程取出各 Notebook 的章节与正文片段，计算 `snapshot_fingerprint`。
2. 任务入 `forest_jobs`，幂等键取指纹，相同输入不重复建任务。
3. Worker 领取后，逐对候选送模型判断是否存在较强联系及类型。
4. 返回值先做端点校验：两端存在、同课程、非同对象、类型在枚举内。
5. 重查两端块指纹，与快照不一致则丢弃该条。
6. 排除已抑制组合与已存在关系后写入 `notebook_relations`，`origin` 标记为 `ai`。
7. 用户删除关系时写抑制记录，后续分析跳过该组合。

培养方案导入：

1. `create_import` 保存源文件或文本，登记 `curriculum_imports`。
2. `extract_curriculum` 先按本地规则解析表格，规则无法覆盖时调用模型，输出严格 JSON。
3. 结果转为预览，逐项标注可新建、可合并、冲突。
4. 用户确认时核对课程 `profile_revision`，未变化才落库。
5. 撤销先创建检查点，再重查期间修改，发现冲突整批拒绝。

#### 3.7.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `list_forest_courses(db)` | `forest/service.py` | 课程树列表 | 返回课程、Notebook 与章节摘要 |
| `ensure_profile(db, course, *, auto_home)` | 同上 | 初始化课程属性 | 已存在则不覆盖用户设置 |
| `update_profile(db, course, *, expected_revision, changes)` | 同上 | 更新展示属性 | 版本不符抛 `ForestConflict` |
| `prepare_course_restore(db, course)` | 同上 | 恢复前整理 | 保持既有首页槽位 |
| `relation_anchor_fingerprint(notebook, block_id)` | 同上 | 锚点指纹 | 返回 SHA-256 或空 |
| `enqueue_notebook_relations(db, course_id, *, notebook_id, processing_route, provider)` | `forest/notebook_relations.py` | 登记关系任务 | 按指纹幂等 |
| `process_notebook_relation_job(job_id)` | 同上 | 执行关系分析 | 无返回值 |
| `candidate_snapshots(db, course_id, *, notebook_id, processing_route)` | `forest/relation_candidates.py` | 候选片段 | 返回快照字典 |
| `snapshot_fingerprint(snapshot)` | 同上 | 快照指纹 | 返回字符串 |
| `create_import(db, *, text, source, filename, processing_route)` | `forest/curriculum.py` | 创建导入 | 返回 `CurriculumImport` |
| `extract_curriculum(db, record, *, client, max_new_steps)` | 同上 | 解析培养方案 | 写入预览，失败抛 `CurriculumError` |
| `claim_next_forest_job()` / `process_forest_job(job_id)` | `forest/jobs.py` | 任务领取与执行 | 原子迁移状态 |
| `create_knowledge_proposal(db, *, course_id, candidate_name, kind, confidence, rationale, ...)` | `knowledge/proposals.py` | 写入提议 | 返回 `KnowledgeProposal` |
| `apply_proposal(db, proposal, *, decision, note)` | 同上 | 接受或拒绝 | 接受则写节点与变更，拒绝写抑制 |
| `add_relation(db, *, course_id, source_node_id, target_node_id, relation_type, confidence, created_by)` | `knowledge/relations.py` | 建边 | 先判环，重复边返回空 |
| `find_candidates(db, *, course_id, name, summary, limit)` | `knowledge/matcher.py` | 相似节点检索 | 返回 `list[MatchCandidate]` |

使用约束：模型推断结果不得直接写 `knowledge_edges`，必须经提议与审核；`add_relation` 不做模糊匹配，名称相似不构成建边依据。

#### 3.7.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `notebook_sections` | 只读 | 课程树来源 |
| `notebooks.document_json` | 只读 | 候选片段来源 |
| `notebook_relations` / 抑制表 | 读写 | 关系与否决 |
| `forest_jobs` | 读写 | 持久任务 |
| `settings` | 读 | 数据目录、解析路线 |

### 3.8 智能答疑与学习工具模块

#### 3.8.1 设计图

```
POST /conversations/{id}/agent-messages（SSE）
        │
        ├─ 会话范围校验（notebook_id / course_id）
        ├─ 检索：正文块 + 解析块（可选联网）
        ├─ build_tool_specs（只读工具集）
        ▼
   run_agent 循环（最多 6 轮）
        ├─ chat_stream（function calling）
        ├─ execute_tool → 检索 / 读页 / 读笔记 / 覆盖 / 术语 / 测验
        └─ 达到轮次上限即收尾
        ▼
   verify_answer（证据门禁）→ claims_for_answer
        ▼
   message_evidence 写入 + 正文发布
```

#### 3.8.2 功能描述

在明确的 Notebook 或课程范围内进行持久问答，回答引用课程内容时附带出处，课外补充与课程依据分开标注。提供术语解释、测验出题与作答、错题与复习产物管理。答疑过程以事件流推送阶段状态与正文增量，回答发布前经过证据核验。

#### 3.8.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| `question` | 请求体 | 非空，长度受限 |
| 会话标识 | 路径 | 会话存在且归属当前范围 |
| `scope` | 会话或请求 | `notebook` 或 `course`；与已绑定会话不一致时按服务端规则拒绝 |
| `material_id` | 请求体 | 可选，指定资料范围；须属于该课程 |
| `reading_context` | 请求体 | 当前阅读位置摘要，作为上下文提示 |
| `allow_web` | 请求体 | 布尔，关闭时不调用检索服务 |
| `history` | 会话记录 | 取最近若干轮，超长截断 |

数据取自 `conversations`、`conversation_messages`（历史）、`notebooks`（正文）、`document_chunks`（解析块）、`notebook_block_sources`（出处）、`web_sources`（联网结果）。

#### 3.8.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| SSE 事件 | `status`、`step`、`delta`、`final`、`notice`、`error` | 见 4.2.2 |
| 消息记录 | 角色、内容、状态、模型版本、过程记录 | 写入 `conversation_messages` |
| 证据 | 来源标识、原文块、页码、片段、支持级别 | 写入 `message_evidence` |
| 学习产物 | 测验、作答记录、复习产物 | 写入相应表 |

#### 3.8.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `conversations` | `id`、`course_id`、`notebook_id`、`title`、`default_scope`、`scope`、`note_id` | 定域会话 |
| `conversation_messages` | `conversation_id`、`role`、`content`、`status`、`model_version`、`failure_type`、`process_json`、`suggestions_json` | 消息与过程 |
| `message_evidence` | `message_id`、`source_ref_id`、`web_source_id`、`claim_key`、`evidence_type`、`support_level`、`document_block_id`、`page_numbers_json`、`parse_run_id`、`notebook_revision`、`snippet` | 证据 |
| `web_sources` | `url`、`title`、`snippet`、`retrieved_at`、`status` | 联网来源 |
| `quizzes` / `quiz_items` / `quiz_attempts` | 题目、选项、答案、判分结果 | 测验 |
| `review_artifacts` | `kind`、`content_json`、`source_refs` | 复习产物 |

#### 3.8.6 算法和流程

1. 校验会话与范围，读取最近历史并截断。
2. 若为笔记本级会话，先读取当前已保存正文，再取该 Notebook 有效归属资料的当前完成解析运行。
3. `build_tool_specs` 按范围与开关生成工具清单：检索、读笔记、读页面、列资料、查覆盖、解释术语、出题、提纲、概念辨析、联网。
4. `run_agent` 进入循环：每轮调用 `chat_stream`，模型返回工具调用时执行 `execute_tool`，把结果截断到 `TOOL_RESULT_MAX_CHARS` 后回填；达到最大轮次即停止并返回已生成内容。
5. 回答生成后调用 `verify_answer`：把答案按段落拆成主张，逐个映射到服务端认可的候选证据；证据不足时保留未核实说明，结构无效或证据冲突则阻止发布。
6. `claims_for_answer` 只保留通过核验的主张映射，写入 `message_evidence`。
7. 通过核验后按 `status`、`delta`、`final` 的顺序推送；未通过则只推送 `status` 与 `notice`，不发送正文。

#### 3.8.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `run_agent(db, *, course_id, course_name, question, scope, locked_notebook_id, editable_notebook_id, reading_context, material_id, allow_web, allow_quiz, history, teacher_persona, conversation_id, learning_mode)` | `ai/agent_loop.py` | 答疑主循环 | 返回事件迭代器 |
| `build_tool_specs(*, scope, editable_notebook, allow_web, allow_quiz, fixed_material_id)` | `ai/agent_tools.py` | 工具清单 | 返回 OpenAI 工具定义列表 |
| `execute_tool(db, *, course_id, name, arguments, scope, locked_notebook_id, editable_notebook_id, allow_web, allow_quiz, conversation_id, fixed_material_id)` | 同上 | 工具分派 | 返回 `ToolOutcome` |
| `arguments_from_json(raw)` | 同上 | 参数解析 | 非法 JSON 返回空字典 |
| `run_notebook_answer(db, *, notebook_id, revision, question, history, allow_web)` | `ai/notebook_qa.py` | 笔记级问答 | 返回事件迭代器 |
| `verify_answer(db, *, answer, chunks, web_results, course_id, scope, client)` | `ai/verified_answer.py` | 证据门禁 | 返回 `VerifiedAnswer`；无法核验抛 `AnswerVerificationError` |
| `extract_claims(answer, chunks, web_results)` | `ai/evidence.py` | 主张拆分 | 每段一条主张 |
| `claims_for_answer(result)` | `ai/notebook_qa.py` | 主张映射 | 只保留服务端批准的证据 |
| `DeepSeekClient.chat_stream(messages, *, tools, max_tokens, temperature)` | `ai/deepseek.py` | 流式调用 | 逐块产出增量与工具调用 |
| `DeepSeekClient.complete_json(messages, *, max_tokens, thinking)` | 同上 | 结构化调用 | 返回解析后的对象 |
| `truncate(text, limit)` | `ai/agent_read_tools.py` | 工具结果截断 | 返回字符串 |
| `_get_source_coverage(db, *, course_id, arguments)` | 同上 | 覆盖查询工具 | 返回逐页状态摘要 |
| `_read_material_page(db, *, course_id, arguments, fixed_material_id)` | 同上 | 读页工具 | 返回该页 IR 文本 |

使用约束：工具集不包含正文写入能力；答疑不得直接修改或删除笔记，改写只能形成待确认建议。

#### 3.8.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `notebooks.document_json` | 只读 | 当前正文，读取时记录版本 |
| `document_chunks` | 只读 | 检索与证据来源 |
| `settings.deepseek_*` | 读 | 模型调用参数 |
| `settings.web_search_timeout_seconds` | 读 | 检索超时 |
| `message_evidence` | 写 | 证据落地 |
| `provider_calls` | 写 | 外部调用记录 |

### 3.9 配置与运行模块

#### 3.9.1 设计图

```
GET/PATCH /settings ──> settings_store
        ├─ build_status（脱敏快照）
        ├─ 白名单校验 → 密钥探活 → _atomic_write(.env) → _apply_to_process
        └─ 失败回滚，保留旧配置

Worker 主循环（runner.main）
        ├─ exclusive_runner_lock（OS 文件锁）
        ├─ mark_interrupted_jobs（启动时修复）
        ├─ claim_next_job（原子领取）
        └─ 每轮按间隔穿插森林与生成协调任务
```

#### 3.9.2 功能描述

管理系统运行配置：默认解析路线、文本与视觉模型、Embedding、超时、上传上限、模型单价与汇率。提供设置读写、连通性测试、图片能力预检与诊断。运行侧提供任务领取、启动恢复、单实例锁与健康检查。费用预算以单个 Asset 为单位做预留与结算。

#### 3.9.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| 设置键值 | 请求体 | 仅允许白名单字段；未知字段拒绝 |
| 设置口令 | 请求头或请求体 | 配置了口令时必须匹配，常量时间比较 |
| API Key | 请求体 | 写入前做一次最小探活；探活失败不覆盖旧值 |
| 任务标识 | Worker 内部 | 状态必须为 `pending` 且未超过尝试上限 |
| 费用请求 | 模型客户端 | 需有生效的 `BudgetContext` 才能预留 |

数据取自 `.env` 文件、`provider_calls`（用量）、`file_processing_budgets`（账本）、`provider_usage_reservations`（预留记录）。

#### 3.9.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 设置状态 | 文本、视觉、Embedding、预算、存储分区与可编辑字段说明 | 密钥只返回掩码 |
| 能力信息 | 支持的格式、大小与页数上限 | 供前端提示 |
| 诊断信息 | 数据库、解析引擎、外部服务可用性 | JSON |
| 预算状态 | `limit_fen`、`settled_fen`、`reserved_fen`、`status` | JSON |
| 健康检查 | `status`、组件状态、版本 | JSON |

#### 3.9.5 数据设计

| 表 | 主要字段 | 说明 |
|---|---|---|
| `file_processing_budgets` | `asset_id`、`currency`、`limit_fen`、`settled_fen`、`reserved_fen`、`status`、`notebook_id` | 单资产账本 |
| `provider_usage_reservations` | `call_id`、`asset_id`、`job_id`、`stage`、`reserved_fen`、`settled_fen`、`status` | 预留与结算 |
| `provider_calls` | `id`、`provider`、`model`、`prompt_tokens`、`completion_tokens`、`created_at` | 调用记录 |

约束：`uq_provider_usage_call_asset`（调用标识与资产唯一），`ix_file_processing_budgets_notebook`（按 Notebook 与状态查询）。配置文件为仓库根 `.env`，键序与注释在覆写时保留。

#### 3.9.6 算法和流程

设置写入：

1. `verify_token` 校验口令，未配置口令时跳过。
2. 遍历更新项，按白名单与类型规则 `_sanitize`，未知键直接拒绝。
3. 若含新密钥，调用 `verify_deepseek_key` 做最小请求探活。
4. `_atomic_write` 先复制当前 `.env` 到 `data/backups/`，再写临时文件并原子替换。
5. `_apply_to_process` 更新进程环境变量与 `settings` 字段，使新值即时生效。
6. 任一步失败直接返回错误，磁盘内容保持原样。

任务调度：

1. 启动时 `mark_interrupted_jobs` 把上次异常退出时仍处于 `processing` 的任务置为 `failed`（`cancel_requested` 置为 `cancelled`），写入中断原因，由用户重试。
2. `exclusive_runner_lock` 以 `data/worker.lock` 取得操作系统级独占锁，第二个进程无法进入循环。
3. `claim_next_job` 用条件更新把 `pending` 改为 `processing`，同时写 `started_at` 与心跳。
4. 每轮按 `FOREST_CHECK_INTERVAL` 与 `GENERATION_COORDINATION_INTERVAL` 穿插森林任务与生成输入协调。
5. 收到停止信号置位 `STOP`，当前任务处理完后退出，不中断事务。

费用预算：

1. `ensure_budget_ready` 校验单价与汇率是否可用，缺失时拒绝付费处理。
2. `_reserve` 按输入上界与最大输出估算费用，原子增加 `reserved_fen`，超额即拒绝。
3. 请求成功后按实际用量 `_settle`，把预留转为已结算。
4. 超时或用量缺失调用 `_mark_uncertain`，保留不确定额度，不做虚假结算。

#### 3.9.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `build_status()` | `core/settings_store.py` | 配置快照 | 密钥掩码，返回字典 |
| `apply_updates(updates, token)` | 同上 | 应用设置 | 返回 `WriteOutcome`，失败抛 `SettingsWriteError` |
| `verify_token(candidate)` | 同上 | 口令校验 | 常量时间比较，返回布尔 |
| `mask_secret(value)` | 同上 | 密钥掩码 | 只暴露长度信息 |
| `verify_deepseek_key(api_key, base_url, timeout)` | 同上 | 密钥探活 | 返回 `(是否可用, 说明)` |
| `_atomic_write(env_values)` | 同上 | 原子写 `.env` | 先备份再替换，返回备份路径 |
| `ensure_budget_ready(kind)` | `services/processing_budget.py` | 预算前置校验 | 价格或汇率缺失时抛 `ProcessingBudgetError` |
| `processing_budget_scope(*, asset_ids, notebook_id, stage, job_id, step_key, kind)` | 同上 | 生效账本 | 上下文管理器 |
| `_reserve(context, *, provider, model, messages, max_tokens)` | 同上 | 预留费用 | 超额拒绝 |
| `_settle(reservation, usage)` | 同上 | 结算 | 按实际用量写入 |
| `pricing_status()` | 同上 | 价格状态 | 返回单价、汇率与时间 |
| `budget_read(asset_id)` | 同上 | 账本读取 | 返回字典或空 |
| `mark_interrupted_jobs(*, force)` | `workers/runner.py` | 启动恢复 | 返回修复条数 |
| `claim_next_job()` | 同上 | 领取任务 | 原子迁移，返回任务标识 |
| `exclusive_runner_lock(path)` | 同上 | 单实例锁 | 上下文管理器 |
| `run_once()` | 同上 | 单轮调度 | 返回是否处理了任务 |

使用约束：`data_dir` 与 `allowed_extensions` 不允许通过设置接口修改；密钥不回显，不写入日志。

#### 3.9.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `settings` | 读写 | 本模块是唯一写入方 |
| `.env` | 读写 | 原子替换，保留注释与键序 |
| `STOP` | 写 | 信号处理置位 |
| `_active_budget`（预算上下文） | 读写 | 模型客户端读取当前账本 |
| `file_processing_budgets` | 读写 | 账本 |
| `provider_usage_reservations` | 读写 | 预留与结算 |

### 3.10 备份恢复模块

#### 3.10.1 设计图

```
POST /backups/export {course_id?}
        ├─ SQLite 在线备份 → 快照文件
        ├─ 按课程裁剪（可选）
        ├─ 收集资产文件 + 计算 SHA-256
        └─ 打包 ZIP（manifest.json + database + assets）

POST /backups/preview（multipart）
        ├─ 格式与路径校验（拒绝绝对路径与 ..）
        ├─ 哈希与大小核对
        ├─ 数据库完整性、外键、引用检查
        └─ 与本地数据比对冲突 → 返回预览

POST /backups/restore（multipart + confirmed=true）
        └─ 重新校验 → 恢复到空目录（不替换当前库）
```

#### 3.10.2 功能描述

导出整个工作区或指定课程的备份包，包含数据库快照、原始资产与清单；对上传的备份包做格式、哈希、完整性与冲突校验；确认后恢复到隔离目录，记录操作结果。备份只读，不修改当前数据库。

#### 3.10.3 输入数据

| 输入项 | 来源 | 校验规则 |
|---|---|---|
| `course_id` | 请求体 | 可选；存在且未删除 |
| 备份文件 | multipart | 必须为 ZIP；包含 `manifest.json` 与数据库文件 |
| `confirmed` | 请求体 | 恢复时必须为 `true` |
| 目标目录 | 服务端决定 | 必须为空，且位于数据目录下 |
| 路径项 | 包内清单 | 拒绝绝对路径、`..` 与符号链接 |

数据取自 `backup_records`（历史）、`assets`（文件清单）、`courses`（课程范围）。

#### 3.10.4 输出数据

| 输出 | 结构 | 说明 |
|---|---|---|
| 备份记录 | 标识、动作、路径、状态、清单摘要 | JSON |
| 备份包 | `manifest.json`、`notebook.sqlite3`、`originals/<文件名>`、`resources/<存储键>` | ZIP |
| 预览结果 | 文件数、总大小、哈希校验、数据库完整性、冲突列表 | JSON |
| 恢复结果 | 目标目录、恢复文件数、校验结论 | JSON |

#### 3.10.5 数据设计

`backup_records` 字段：`id`、`course_id`、`action`（`export` / `preview` / `restore`）、`path`、`status`、`manifest_json`、`error_message`、`created_at`、`completed_at`。

`manifest.json` 结构：

```
{
  "format": 2,
  "created_at": "2026-11-10T05:00:00+00:00",
  "database_sha256": "...",
  "course_count": 1,
  "material_count": 6,
  "originals": [{"name": "xxx.pdf", "bytes": 12345, "sha256": "..."}],
  "assets": [{"key": "notebooks/<id>/images/xxx.png", "bytes": 6789, "sha256": "..."}],
  "derived_indexes": "omitted; rebuild from SQLite pages"
}
```

包内不包含 `.env` 与任何密钥文件；派生索引不打包，恢复后由数据库内容重建。

#### 3.10.6 算法和流程

导出：

1. 调用 SQLite 备份接口生成一致性快照，避免直接复制活跃库。
2. 指定课程时在快照上执行裁剪，只保留该课程的课程、Notebook、资料、解析与来源数据。
3. 按 `assets.storage_key` 收集文件，逐个计算 SHA-256 与大小。
4. 写入清单，按清单顺序打包：先 `manifest.json`，再数据库快照，最后逐个写入原件与资源文件。
5. 记录 `backup_records`，返回路径与摘要。

预览：

1. 打开 ZIP，读取清单，校验 `format` 字段与 `created_at`。
2. 逐项校验路径合法性：拒绝绝对路径、`..`、越界目标。
3. 解压到临时目录，逐个比对大小与 SHA-256。
4. 对数据库执行 `PRAGMA integrity_check` 与 `foreign_key_check`。
5. 比对包内原始文件名与本地数据，输出冲突列表。
6. 清理临时目录，返回预览结果。

恢复：

1. 重复预览的全部校验。
2. 要求目标目录为空且位于数据目录下。
3. 解压到目标目录，逐文件核对哈希。
4. 校验数据库可读、表结构版本匹配。
5. 记录结果；当前数据库保持不变。

#### 3.10.7 函数说明

| 函数 | 文件 | 作用 | 主要参数与返回 |
|---|---|---|---|
| `create_backup_archive(data_dir, destination, *, course_id)` | `services/backup.py` | 生成备份包 | 返回清单摘要 |
| `preview_backup(path, *, current_database)` | 同上 | 校验与预览 | 返回校验结果与冲突列表 |
| `restore_backup_to_empty(path, destination)` | 同上 | 隔离恢复 | 返回恢复摘要 |
| `_snapshot(database, destination)` | 同上 | 数据库快照 | 使用 SQLite 备份接口 |
| `_filter_snapshot_to_course(database, course_id)` | 同上 | 按课程裁剪 | 只改快照副本 |
| `_asset_entries(database, data_dir)` | 同上 | 资产清单 | 返回文件、大小与哈希 |
| `_read_manifest(archive)` | 同上 | 读清单 | 格式不符抛异常 |
| `_database_conflicts(database, manifest)` | 同上 | 原始文件冲突 | 返回冲突列表 |
| `_course_conflicts(package_db, current_db)` | 同上 | 课程级冲突 | 返回冲突列表 |
| `_archive_sha256(archive, member)` | 同上 | 流式哈希 | 返回 `(哈希, 大小)`，不整文件读入内存 |

使用约束：恢复目标必须是空目录；任何情况下不覆盖当前数据库；导出与预览均为只读操作。

#### 3.10.8 全局数据结构与该模块的关系

| 全局数据 | 读写 | 说明 |
|---|---|---|
| `settings.data_dir` | 读 | 数据库、资产、备份目录定位 |
| `assets.storage_key` | 只读 | 资产文件定位 |
| `backup_records` | 写 | 操作留痕 |
| `notebooks` / `materials` / `document_*` | 只读 | 备份内容 |

## 4 接口设计

### 4.1 用户接口

界面按功能分区，均通过浏览器访问本地服务：

| 界面 | 页面组件 | 主要操作 | 交互要点 |
|---|---|---|---|
| 首页 | `HomePage` | 课程卡片、最近打开、新建课程 | 空态给出上传引导 |
| 课程库 | `CourseLibraryPage` | 课程增删改、Notebook 排序与绑定 | 删除前弹出影响预览 |
| 课程总览 | `CourseOverviewPage` | 资料与笔记汇总、进入工作区 | 汇总数与实际记录一致 |
| 资料管理 | `MaterialsPage` | 拖拽上传、讲次命名、解析状态、重试与换路线 | 批次进度按文件展示，失败给原因 |
| Notebook 工作区 | `NotebookPage` | 左目录、中正文、右答疑坞；富文本、表格、公式、图片、历史版本 | 目录与正文联动滚动，自动保存并显示版本，冲突提示刷新 |
| 知识森林 | `ForestPage`、`CourseKnowledgeStructure` | 课程树、关系列表、关系分析入口 | 节点可展开，点击定位正文 |
| 助手 | `AssistantPage` | 会话列表、提问、出处与过程展示 | 阶段状态先于正文出现 |
| 回收站 | `RecycleBinPage` | 恢复、永久删除 | 危险操作二次确认 |
| 设置与备份 | 设置面板 | 模型与路线、连通性测试、预算与诊断、备份导出与预览 | 密钥只显示掩码 |

### 4.2 外部接口

#### 4.2.1 HTTP 接口

统一前缀 `/api/v1`，请求与响应为 JSON，上传与备份为 multipart。下表按资源分组列出主要端点。

| 资源 | 方法与路径 | 说明 |
|---|---|---|
| 课程 | `GET /courses`、`POST /courses`、`PATCH /courses/{id}`、`DELETE /courses/{id}` | 列表、新建、修改、软删除 |
| 课程 | `GET /courses/{id}/overview`、`GET /courses/{id}/deletion-preview`、`GET /courses/deleted` | 总览、删除预览、回收站 |
| 笔记本 | `GET /notebooks/unbound`、`POST /notebooks/unbound`、`GET /courses/{id}/notebooks` | 未分类与课程内列表 |
| 笔记本 | `POST /courses/{id}/notebooks`、`PATCH /courses/{cid}/notebooks/{id}`、`DELETE /courses/{cid}/notebooks/{id}` | 新建、重命名、删除 |
| 笔记本 | `GET/PATCH/DELETE /notebooks/unbound/{id}`、`GET/PUT /notebooks/unbound/{id}/document` | 未分类笔记本及其正文 |
| 笔记本 | `PATCH /courses/{cid}/notebooks/{id}/order` | 章节排序，带 `expected_order_revision` |
| 笔记本 | `POST /notebooks/{id}/bind`、`POST /notebooks/{id}/unbind`、`POST /notebooks/{id}/move` | 归属变更 |
| 正文 | `GET /courses/{cid}/notebooks/{id}/document`、`PUT` 同路径 | 读取与保存，保存带 `expected_revision` |
| 正文 | `GET /courses/{cid}/notebooks/{id}/sections`、`GET /notebooks/{id}/blocks/{bid}/sources` | 目录与来源 |
| 修订 | `GET /courses/{cid}/notebooks/{id}/revisions`、`POST .../revisions/{rev}/restore` | 历史与恢复 |
| 资料 | `POST /notebooks/{id}/assets`、`GET /notebooks/{id}/assets`、`DELETE .../assets/{aid}` | 上传、列表、删除 |
| 资料 | `POST /notebooks/{id}/upload-batches/{bid}/complete` | 批次完成 |
| 解析 | `GET /assets/{id}/document`、`GET /assets/{id}/document/runs/{run_id}` | 当前与历史解析 |
| 解析 | `GET /assets/{id}/document/pages/{n}/render`、`GET /assets/{id}/document/pages/{n}/evidence` | 页图与页证据 |
| 解析 | `GET /assets/{id}/parse-runs`、`GET /assets/{id}/parse-results` | 运行记录与结果 |
| 生成 | `POST /notebooks/{id}/generation-jobs`、`GET /notebooks/{id}/generation-jobs` | 创建与列表 |
| 生成 | `POST .../generation-jobs/{jid}/retry`、`POST .../{jid}/cancel` | 重试与取消 |
| 覆盖 | `GET /materials/{id}/coverage`、`GET /assets/{id}/document/coverage` | 逐页覆盖 |
| 森林 | `GET /forest`、`GET /forest/courses/{id}/tree`、`GET /forest/search` | 课程树与搜索 |
| 森林 | `GET /forest/relations`、`POST /forest/relations`、`DELETE /forest/relations/{id}` | 关系管理 |
| 森林 | `POST /forest/courses/{id}/suggest-relations`、`GET /forest/jobs/{id}` | 关系分析与任务 |
| 培养方案 | `POST /forest/curriculum-imports`、`GET .../{id}`、`POST .../{id}/confirm` | 导入、查看、确认 |
| 会话 | `GET /conversations/{id}/messages`、`POST /conversations/{id}/agent-messages` | 历史与流式提问 |
| 学习工具 | `GET /courses/{id}/quizzes`、`GET /quizzes/{id}`、`POST /quizzes/{id}/attempts`、`GET /courses/{id}/quiz-mistakes` | 测验、作答与错题 |
| 设置 | `GET /settings`、`PATCH /settings`、`GET /config/capabilities`、`GET /config/diagnostics` | 配置与能力 |
| 备份 | `POST /backups/export`、`POST /backups/preview`、`POST /backups/restore` | 导出、预览、恢复 |
| 任务 | `GET /jobs/{id}`、`GET /materials/{id}/latest-job` | 状态查询 |
| 健康 | `GET /health` | 组件状态 |

#### 4.2.2 流式接口

答疑使用 `text/event-stream`，事件顺序如下：

| 事件 | 载荷 | 触发时机 |
|---|---|---|
| `status` | `status`（`thinking` 或核验模式） | 开始推理、核验完成等阶段切换 |
| `step` | `tool`、`detail`、`status`（`running` / `done`） | 工具调用开始与完成 |
| `delta` | `text` | 正文增量 |
| `final` | `answer`、`sources`、`suggestions`、`mode`、`model_version` | 回答结束，随写入库 |
| `notice` | 提示文本 | 能力受限、证据不足等说明 |
| `error` | `message` | 失败，由前端提示可重试 |

传输格式为 `data: {JSON}\n\n`，事件类型在 JSON 的 `type` 字段中，不使用 `event:` 行。核验完成前不发送 `delta`。

#### 4.2.3 外部服务接口

| 服务 | 协议与路径 | 用途 | 约束 |
|---|---|---|---|
| 文本模型 | `POST {base_url}/chat/completions` | 生成、规划、答疑、关系判断 | 超时 60 秒，有限重试，遵守预算闸门 |
| 视觉模型 | 兼容 Chat Completions 的多模态请求 | 直读路线与图片页解析 | 需通过图片能力预检 |
| Embedding | `POST {base_url}/embeddings` | 检索向量 | 可选，未配置时退化为关键词检索 |
| 联网检索 | Tavily HTTP 接口 | 课外补充证据 | 超时 20 秒，结果写入 `web_sources` |

浏览器不持有任何密钥，所有外部调用由服务端发起。

### 4.3 内部接口

#### 4.3.1 接口说明

| 调用方 → 被调方 | 接口 | 输入 | 输出 | 异常 |
|---|---|---|---|---|
| 路由 → 课程服务 | `bind_notebook` / `unbind_notebook` / `move_notebook` | 笔记标识、课程标识 | `Notebook` | 课程不存在 404、归属冲突 409 |
| 路由 → 上传服务 | `ingest_document` | 文件流、笔记标识、路线、幂等键 | `(Material, ProcessingJob)` | 415 / 413 / 409 / 422 |
| Worker → 解析服务 | `create_parse_run` / `execute_parse_run` | 资产、配置、进度回调 | `ParseOutcome` | `UnsupportedDocument` |
| 生成 → 解析 | `load_ir` / `current_run` | 运行标识或资产标识 | `DocumentIR` | 运行不存在 |
| 生成 → 正文 | `write_document` | 正文、`expected_revision`、来源 | `(revision, document)` | `DocumentConflict`、`DocumentValidationError` |
| 正文 → 森林 | `enqueue_notebook_relations` | 课程标识、笔记标识 | 任务标识 | — |
| 答疑 → 解析 | `_read_material_page` | 资料标识、页号 | 页文本与结构 | 页不存在 |
| 答疑 → 正文 | `_read_notebook` | 笔记标识、范围 | 正文片段 | 越权返回空 |
| 答疑 → 核验 | `verify_answer` | 答案、候选块、联网结果 | `VerifiedAnswer` | `AnswerVerificationError` |
| 备份 → 数据库 | `_snapshot` | 库路径、目标路径 | 快照文件 | 磁盘错误 |

#### 4.3.2 调用方式

正文写入（所有正文修改的唯一入口）：

```python
from app.notes.store import write_document, DocumentConflict

revision, document = write_document(
    db,
    notebook,
    content,                      # ProseMirror JSON 对象
    expected_revision=12,         # 当前版本，来自客户端或任务基准
    origin="autosave",            # autosave / restore / generation
    refresh_relations=True,       # 正文变化后登记关系候选
)
```

上传受理（请求进程只登记，不解析）：

```python
from app.services.uploads import ingest_document, UploadRejected

try:
    material, job = ingest_document(
        db,
        course_id=course_id,
        source=upload.file,       # 支持 read(size) 的文件对象
        filename=upload.filename,
        lecture_title=lecture_title or "",
        topic_title=None,
        media_type=upload.content_type,
        notebook_id=notebook_id,  # 必须显式给出
        idempotency_key=request.headers.get("Idempotency-Key"),
        processing_route="standard",
    )
except UploadRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))
```

生成任务创建：

```python
from app.services.generation_jobs import create_generation_job

job = create_generation_job(
    db,
    notebook_id=notebook_id,
    asset_ids=asset_ids or None,   # None 表示该笔记全部就绪资料
    idempotency_key=request.headers.get("Idempotency-Key"),
)
```

答疑流式调用：

```python
from app.ai.agent_loop import run_agent

events = run_agent(
    db,
    course_id=course_id,
    course_name=course.name,
    question=question,
    scope="notebook",
    locked_notebook_id=notebook_id,
    allow_web=True,
)

def _sse(event: dict) -> str:
    # 事件类型在 JSON 的 type 字段，SSE 只承载 data 行
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

return StreamingResponse((_sse(e) for e in events), media_type="text/event-stream")
```

## 5 数据库设计

### 5.1 数据库系统

采用 SQLite 单文件数据库，位置 `data/notebook.sqlite3`，通过 SQLAlchemy 2.0 ORM 访问，Alembic 管理结构演进。选择理由是该系统为本机单用户应用，SQLite 免部署、支持事务与在线备份，且与文件目录同处一地便于整体迁移与备份。

连接配置：

| 项目 | 取值 |
|---|---|
| 驱动 | `sqlite:///<data_dir>/notebook.sqlite3` |
| 事务 | 会话级，路由或 Worker 决定提交时机 |
| 外键 | 每个连接执行 `PRAGMA foreign_keys=ON` |
| 日志模式 | `journal_mode=WAL`、`synchronous=NORMAL` |
| 锁等待 | `busy_timeout` 秒级等待，避免瞬时并发直接报错 |
| 并发 | 单写多读；写操作通过条件更新与写锁串行化 |
| 备份 | 使用 SQLite 在线备份接口，不直接复制活跃库 |

### 5.2 数据表设计

共 58 张业务表，按职责分组：

| 数据组 | 表 | 职责 |
|---|---|---|
| 学习组织 | `courses`、`notebooks`、`notebook_reading_positions` | 课程、笔记本、阅读位置 |
| 资源登记 | `assets`、`materials`、`notebook_assets`、`notebook_upload_batches`、`notebook_attachments`、`notebook_cover_assets`、`notebook_revision_assets` | 文件身份、讲次、归属、附件与封面 |
| 原始证据 | `document_parse_runs`、`document_pages`、`document_blocks`、`document_sections`、`document_chunks` | 解析版本、页、块、小节、检索块 |
| 正文追踪 | `notebook_document_revisions`、`notebook_block_sources`、`notebook_sections`、`notebook_edit_suggestions` | 历史快照、来源映射、目录、编辑建议 |
| 生成与任务 | `notebook_generation_jobs`、`notebook_generation_inputs`、`notebook_generation_candidates`、`processing_jobs`、`processing_steps`、`asset_processing_jobs`、`asset_parse_results`、`asset_migration_issues` | 任务、输入、候选、步骤检查点 |
| 费用 | `file_processing_budgets`、`provider_usage_reservations`、`provider_calls` | 账本、预留、调用记录 |
| 知识导航 | `forest_course_profiles`、`forest_jobs`、`curriculum_imports`、`cross_course_relations`、`notebook_relations`、`notebook_relation_suppressions`、`knowledge_nodes`、`knowledge_edges`、`knowledge_proposals`、`knowledge_changes` | 课程树、关系、培养方案、知识点 |
| 交互与学习 | `conversations`、`conversation_messages`、`message_evidence`、`web_sources`、`quizzes`、`quiz_items`、`quiz_attempts`、`review_artifacts`、`feedback` | 会话、证据、测验与复习 |
| 兼容与运维 | `notes`、`note_revisions`、`note_source_mappings`、`note_suggestions`、`source_refs`、`retrieval_chunks`、`material_pages`、`page_blocks`、`backup_records` | 旧版兼容、历史引用、备份记录 |

核心表的字段构成：

| 表 | 主键 | 关键字段 |
|---|---|---|
| `courses` | `id` | `name`、`description`、`deleted_at`、`notebook_order_revision`、`last_opened_at` |
| `notebooks` | `id` | `course_id`、`title`、`display_order`、`order_revision`、`document_json`、`document_revision`、`is_default`、`tree_slot`、`deleted_at` |
| `notebook_document_revisions` | `id` | `notebook_id`、`revision`、`schema_version`、`document_json`、`origin`、`retention` |
| `notebook_sections` | `id` | `notebook_id`、`course_id`、`block_id`、`order`、`level`、`heading`、`text`、`revision` |
| `notebook_block_sources` | `id` | `notebook_id`、`block_id`、`generation_job_id`、`parse_run_id`、`document_block_id`、`page_number`、`body_fingerprint`、`status` |
| `assets` | `id` | `storage_key`、`original_name`、`extension`、`mime_type`、`byte_size`、`sha256`、`state`、`processing_route` |
| `materials` | `id` | `notebook_id`、`course_id`、`asset_id`、`lecture_title`、`chapter_order`、`status`、`page_count`、`content_hash`、`deleted_at` |
| `document_parse_runs` | `id` | `asset_id`、`status`、`parser_name`、`parser_version`、`config_version`、`is_current`、`fingerprint`、`quality_status`、`supersedes_id` |
| `document_pages` | `id` | `parse_run_id`、`page_number`、`logical_page_id`、`render_key`、`extraction`、`status`、`text`、`confidence` |
| `document_blocks` | `id` | `parse_run_id`、`page_id`、`block_id`、`parent_block_id`、`order`、`global_order`、`block_type`、`level`、`text`、`latex`、`table_json`、`figure_json` |
| `document_chunks` | `id` | `parse_run_id`、`asset_id`、`order`、`text`、`page_numbers_json`、`block_ids_json`、`embedding_json` |
| `notebook_generation_jobs` | `id` | `notebook_id`、`idempotency_key`、`status`、`base_document_revision`、`input_snapshot_json`、`knowledge_plan_json`、`source_map_json`、`attempt_count`、`error_code` |
| `conversations` | `id` | `course_id`、`notebook_id`、`title`、`default_scope`、`scope` |
| `conversation_messages` | `id` | `conversation_id`、`role`、`content`、`status`、`model_version`、`process_json` |
| `message_evidence` | `id` | `message_id`、`source_ref_id`、`web_source_id`、`claim_key`、`evidence_type`、`support_level`、`document_block_id`、`page_numbers_json`、`parse_run_id`、`snippet` |
| `backup_records` | `id` | `course_id`、`action`、`path`、`status`、`manifest_json`、`error_message` |

完整字段与类型见 2.3 及各模块 3.x.5；`notes`、`note_revisions`、`note_source_mappings` 仅承担兼容与历史引用职责，不作为正文来源。

### 5.3 索引与约束

除主键与外键索引外，关键约束如下：

| 约束/索引 | 表 | 作用 |
|---|---|---|
| `uq_notebooks_course_slot` | `notebooks` | 同一课程内槽位唯一 |
| `uq_notebooks_default`（部分唯一） | `notebooks` | `is_default = 1` 时课程内仅一本默认 |
| `uq_notebook_document_revisions` | `notebook_document_revisions` | 笔记与版本组合唯一 |
| `uq_materials_asset_id` | `materials` | 一个资产对应一条讲次记录 |
| `uq_notebook_attachments_asset_id` | `notebook_attachments` | 附件与资产一一对应 |
| 活动归属部分唯一索引 | `notebook_assets` | `is_owner = 1 AND detached_at IS NULL` 时唯一 |
| `uq_notebook_relations_endpoints_anchors` | `notebook_relations` | 两端、类型与锚点组合唯一 |
| `uq_processing_steps` | `processing_steps` | 作用域、阶段、步骤键与指纹唯一 |
| `uq_processing_jobs_idempotency_key` | `processing_jobs` | 幂等键唯一，重复提交返回原任务 |
| `uq_provider_usage_call_asset` | `provider_usage_reservations` | 调用与资产组合唯一 |
| `uq_processing_jobs_active_material`（部分唯一） | `processing_jobs` | `status IN ('pending','processing')` 时同一资料仅一个未完成任务 |
| `uq_asset_processing_jobs_active`（部分唯一） | `asset_processing_jobs` | `status IN ('pending','processing')` 时同一资产仅一个活动任务 |
| `uq_document_parse_runs_current`（部分唯一） | `document_parse_runs` | `is_current = 1` 时同一资产仅一个当前运行 |

部分唯一索引通过 `sqlite_where` 实现，用于表达"同一对象只允许一个活动记录"这类业务约束，使并发提交在数据库层即被拒绝。

### 5.4 存储设计

| 存储对象 | 位置 | 访问方式 | 说明 |
|---|---|---|---|
| 业务数据 | `data/notebook.sqlite3` | ORM，按主键与索引 | 行级读写，事务提交 |
| 原始课件 | `data/originals/<material_id><扩展名>` | 按 `storage_key` 直接定位 | 整份读取，不修改 |
| 派生页图 | `data/derived/<run_id>/` | 按运行与页号 | 可重建，缺失时按需生成 |
| 正文图片 | `data/notebooks/<id>/images/` | 按附件标识 | 引用计数由正文决定 |
| 暂存文件 | `data/staging/` | 临时命名 | 成功后原子改名 |
| 备份 | `data/backups/` | 按时间戳 | 整包读写 |
| 日志 | `data/logs/` | 按日期与进程 | 追加写 |

存取单位与顺序：数据库以行为单位，一次编辑一个事务；文件以整份为单位，替换时写临时文件再改名；解析结果按"运行"隔离，新运行不覆盖旧运行的页块。

## 6 系统出错处理

### 6.1 出错信息

| 场景 | 状态码/错误码 | 输出形式 | 处理方式 |
|---|---|---|---|
| 文件扩展名不在白名单 | 415 | `detail` 文本 | 提示支持格式，不落盘 |
| 文件超过大小上限 | 413 | `detail` 含上限值 | 中断写入并删除临时文件 |
| PDF 页数超过路线限制 | 413 | `detail` 含页数上限 | 同上 |
| PDF 签名与扩展名不符 | 415 | `detail` 文本 | 拒绝入库 |
| ZIP 结构损坏（PPTX/DOCX） | 415 | `detail` 文本 | 拒绝入库 |
| 重复上传同一文件 | 409 | `detail` 含已存在讲次标题 | 可确认后作为新讲次导入 |
| 幂等键重复 | — | 返回原任务 | 不新建记录 |
| 笔记不属于指定课程 | 409 | `detail` 文本 | 拒绝操作 |
| 未指定笔记本 | 422 | `detail` 文本 | 要求显式选择 |
| 直读路线未通过视觉预检 | 409 | `detail` 含缺失配置 | 提示先完成配置 |
| 正文结构非法 | 422 | `detail` 指出违规类型 | 不写入，前端保留草稿 |
| 正文超限（节点/深度/字节） | 422 | `detail` 指出超限项 | 不写入 |
| 正文版本冲突 | 409 | `detail` 提示刷新 | 不覆盖，客户端重新拉取 |
| 图片不属于该笔记 | 422 | `detail` 文本 | 拒绝保存 |
| 修订不存在 | 404 | `detail` 文本 | 提示版本已裁剪 |
| 生成输入无效（资产缺失或未解析） | 422/409 | `detail` 含资产标识 | 任务不创建 |
| 生成期间正文被编辑 | — | 无对外错误 | 回滚本次追加并重新合并，只追加不覆盖；多次冲突后任务失败 |
| 模型输出结构非法 | 任务 `error_code=document_format_repair_failed` | 任务详情含首次与修复后错误 | 自动修复一次仍未通过则失败，不写入正文 |
| 公式校验未通过 | 任务 `error_code=invalid_inline_math` 等 | 任务详情含失败码计数 | 不写入正文 |
| 来源映射缺失或越界 | 任务 `error_code=invalid_sources` | 任务详情 | 不写入正文 |
| 生成结果为空 | 任务 `error_code=empty_generation` | 任务详情 | 提示资料可能已全部覆盖 |
| 答疑证据不足 | `status` 或 `notice` 事件 | 流式提示 | 保留未核实说明，不发布未经核验内容 |
| 答疑核验失败 | `error` 事件 | `code` + `message` | 结束本次回答，可重试 |
| 模型服务不可用 | 502/504 或任务失败 | `detail` 或任务错误 | 有限重试后降级或失败 |
| 检索超时 | — | 忽略该来源 | 继续以课程证据回答 |
| 预算不足 | 409/422 | `detail` 含余额 | 拒绝付费处理 |
| 单价或汇率不可用 | 422 | `detail` 指明缺失项 | 拒绝付费处理 |
| 备份格式不符 | 422 | `detail` 文本 | 不恢复 |
| 备份哈希不一致 | 422 | `detail` 含文件路径 | 不恢复 |
| 备份路径越界 | 422 | `detail` 文本 | 拒绝并要求重新打包 |
| 恢复目标非空 | 409 | `detail` 文本 | 不写入 |
| 存在活动任务时删除 | 409 | `detail` 含任务数 | 提示等待或取消 |
| 课程或笔记不存在 | 404 | `detail` 文本 | 前端回列表 |
| 设置口令错误 | 403 | `detail` 文本 | 不写入配置 |

### 6.2 补救措施

**任务失败。** 任务表保留 `error_code`、`error_message`、`attempt_count` 与快照。用户可在界面触发重试，重试复用 `processing_steps` 中已完成的模型步骤，仅重跑失败批次。已消费的输入记录在 `notebook_generation_inputs`，重试不会重复消费同一资产。

**进程异常退出。** 启动时 `mark_interrupted_jobs` 把上次异常退出时仍处于 `processing` 的任务置为 `failed` 并写入中断原因，由用户重试；`exclusive_runner_lock` 保证同一时刻只有一个 Worker 在写。若上次任务已写入部分结果，正文的 CAS 与来源映射的事务性保证不会出现半成品。

**正文冲突。** 保存请求携带 `expected_revision`，冲突时不写入并返回 409。生成任务同样以基准版本合并，冲突时任务失败而不是覆盖。客户端的未提交草稿保留在本地，用户可复制后刷新。

**数据损坏或误删。** 课程与资料采用软删除，回收站可恢复；删除前生成检查点。备份模块支持导出与隔离恢复，恢复在校验通过后写入空目录，用户确认后再替换工作目录。派生数据（章节、检索块、森林目录）可由正文与解析结果重建，不依赖备份。

**外部服务不可用。** 模型调用失败按次数上限重试；仍未成功时任务失败并给出可读原因，既有正文与解析结果不受影响。联网检索失败仅影响课外证据，课程内证据仍可用于回答。

**磁盘写入中断。** 上传使用临时文件加原子改名，不产生半截原件；`reconcile_staged_document_assets` 在服务启动后扫描落盘与入库之间的不一致并修复或隔离。

## 7 其他设计

### 7.1 安全设计

**边界。** 系统按本机单用户设计，服务绑定 `127.0.0.1`，不对外提供网络访问；浏览器不接触数据库、文件系统与密钥。

**归属校验。** 每个涉及课程、笔记本、资料、块、修订的请求都在服务端重新校验归属，不信任前端传入的课程标识。跨笔记本引用一律拒绝，答疑的检索范围由会话绑定的笔记决定，切换页面不构成扩大范围。

**路径校验。** 文件访问只通过数据库中的 `storage_key` 解析到数据目录下的固定子目录，拼接后校验结果仍位于该目录内；备份包内路径拒绝绝对路径、`..` 与越界目标。

**密钥与配置。** 密钥只存于本地 `.env`，接口返回掩码；写配置前做一次最小探活，避免写入不可用密钥；日志只记录任务标识、状态、时间与错误类别，不记录请求体与密钥。

**内容处理。** 用户资料、网页内容与模型输出均按数据处理，不作为指令执行。模型输出先经结构与证据校验再入库，答疑正文在核验通过后才推送。

**删除保护。** 软删除与解绑保留语义；永久删除有独立入口，且要求对象已处于软删除状态；存在活动任务时拒绝删除。

### 7.2 性能设计

**检索与上下文控制。** 生成按知识单元与字符预算分批（单批 18000 字符、总计 120000 字符），分批在原块边界切分，不切断表格与公式；答疑工具结果统一截断（`TOOL_RESULT_MAX_CHARS`），避免上下文膨胀。检索优先使用当前完成的解析运行，减少无效候选。

**写入路径。** 正文整份读写，避免块级合并带来的顺序问题；章节、检索块、森林目录为派生数据，重建成本随文档规模线性增长，保存时全量重建一次。索引覆盖常用查询：按 Notebook 与时间读取修订、按资产与状态读取预算、按状态与更新时间领取任务。

**长任务。** 上传与生成异步化，请求只登记任务即返回；解析逐页回调进度，界面可显示已处理页数。Worker 单实例串行执行，避免多进程争抢 SQLite 写锁。

**数据库。** 单写多读，写操作使用条件更新与短事务；避免在事务内做模型调用，模型调用前后分别读写，缩短锁持有时间。

**前端。** 重型功能按路由拆分并延迟加载；加载、空数据、处理中与失败四种状态均有占位与提示，避免空白等待。

### 7.3 可维护性

**分层与边界。** 路由负责接入与校验，服务负责用例编排，领域模块负责具体能力，`workers` 只做任务调度。新增解析器只需实现 `parsers/base.py` 的接口并在 `service.py` 注册，不改动生成与正文逻辑。

**契约集中。** 请求与响应由 `schemas` 的 Pydantic 模型定义；解析结果由 `DocumentIR` 统一，新增字段需同步 `to_dict`、`from_dict` 与 `validate`；正文结构约束集中在 `notes/document.py`。

**可测试点。** 纯函数（`build_plan`、`inspect_generated_math`、`build_sections`、`body_fingerprint`、`snapshot_fingerprint`）可独立单测；涉及数据库的部分通过隔离数据库与真实迁移演练；流式答疑与任务进度通过事件序列断言。

**演进约束。** 已发布的迁移不改写，结构变更新增版本；`notes` 系列旧表只做兼容，不恢复为权威正文；新增模块间调用需在本文档第 4 章补充接口说明，避免出现文档未记录的隐式契约。
