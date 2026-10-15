# API 契约

## 多笔记本与续读（2026-10-15）

以下地址均使用 `/api/v1` 前缀。每个本、章节、笔记读写同时校验课程与笔记本归属，越界返回 404。

| 接口 | 契约 |
| --- | --- |
| `GET/POST /courses/{course_id}/notebooks` | 列出/创建笔记本；创建体 `{title}`，201 返回 `NotebookSummary`：`id,course_id,title,tree_slot,display_order,order_revision,is_default,created_at,updated_at`。空课程返回空列表，不在读取时创建默认本 |
| `GET/PATCH /courses/{course_id}/notebooks/{notebook_id}` | 返回 `NotebookRead`：`id,course_id,title,tree_slot,order_revision,chapters,historical_sections,removed_chapters`；PATCH 体 `{title}`。目录不含正文 |
| `GET .../notebooks/{notebook_id}/chapters/{material_id}` | 返回 `material_id,sections: NoteRead[]`；跨本、跨课或已移除章节返回 404 |
| `PATCH .../notebooks/{notebook_id}/order` | `{material_ids,expected_order_revision}`，必须完整列出本内活动章节；过期409、无效列表422。上传、移除、恢复只递增所属本目录版本 |
| `GET/PUT .../notebooks/{notebook_id}/reading-position` | GET 无记录返回 null。PUT 体 `{chapter_id,note_id,mode,section_offset,expected_revision}`，mode 为 chapter/book，offset 为 0..1；首次 expected_revision=0，成功返回 notebook_id、上述位置、新 revision 与 updated_at；冲突409 |
| `POST /courses/{course_id}/visit` | 服务端记录实际访问时间并返回 `{last_opened_at}`；课程查询包含该字段，后台生成与森林悬停不登记访问 |
| `GET /forest/courses/{course_id}/tree` | `{course_id,notebooks: NotebookRead[]}`；首页/森林共用轻量目录，不读取正文 |

上传 multipart 增加 `notebook_id`；多本课程必须明确目标，省略时仅单本兼容（空课程需先创建本）。重复文件检查和上传幂等键均包含本 ID：同本重复须显式确认，异本可分别导入。`MaterialRead`、`NoteRead`、`SectionRead` 和森林笔记搜索结果均包含 `notebook_id`；小节还包含持久 `tree_slot`，不因重排改变。书签保存采用乐观并发，可信本地 CORS 已允许 PUT；正文保存版本与书签版本独立。

Web 路由为 `/courses/:courseId/notebooks/:notebookId?chapter=<materialId>&section=<noteId>`，整本模式加 `mode=book`，历史整理用 `chapter=history`。叶子和搜索深链优先于旧书签；枝干恢复该本书签，失败保留待重试位置并提示。目标已移除时回到原本目录，不转到别本。旧单数 API 指向默认本；真正空课返回404，不自动写库。旧单数阅读路由和 `/courses/:courseId/notes/:noteId` 按真实Note归属解析。

前端画布快照 `KnowledgeTreeView` 可选 `knownNotebookIds: Record<courseId,string[]>`，用于跨上传页返回时识别新增主枝，属于本地session视图数据，不是后端API字段。无该字段的旧缓存首次不播放全树生长；新增枝600ms反馈遵守reduced-motion。

## 课程笔记本历史契约（2026-10-08）

本段记录旧单本契约；单数接口通过默认本兼容。多本作用域、空课与显式新路由以上方2026-10-15契约为准。

以下地址使用 `/api/v1` 前缀。

| 接口 | 契约 |
| --- | --- |
| `GET /courses/{course_id}/notebook` | 目录：`course_id`、`title`、`order_revision`、活动 `chapters`、`historical_sections`、`removed_chapters`。章节按 `chapter_order`，小节按 `section_order` 排序；目录不包含正文 |
| `GET /courses/{course_id}/notebook/chapters/{material_id}` | 本课程活动章节的 `material_id` 与 `sections: NoteRead[]`；不存在、跨课程或移除章节返回 404 |
| `PATCH /courses/{course_id}/notebook/order` | `material_ids` 必须完整列出本课程活动章节且无重复；`expected_order_revision` 是当前目录版本。成功返回新目录；过期返回 409，无效列表返回 422 |

上传、移除及恢复资料均递增目录版本。NoteRead 增加 `material_id`（历史笔记可空）、`section_key`、`section_order`；原笔记 ID、保存版本号、历史与来源接口保持兼容。知识图增加 `occurrences`，每项 `id=note_id`，同时包含概念 ID、资料 ID、稳定小节键、顺序和标题；同概念可以对应多个讲次小节。本讲笔记的网络来源限制在其 material_id。

历史整理的网络来源按笔记实际课件来源中的资料集合筛选；无法确定资料范围时返回空列表，不能返回概念在所有讲次中的来源。

Web 定位：`/courses/:courseId/notebook?chapter=<materialId>&section=<noteId>`；历史小节用 `chapter=history`，整本模式加 `mode=book`（包含所有历史整理正文）。旧 `/courses/:courseId/notes/:noteId` 按原 ID 转入对应位置。正文保存仍使用乐观版本号，AI 重解析变化只创建建议。

现有 `/api/v1` 地址保持不变。路由按 `courses.py`、`materials.py`、`jobs.py`、`knowledge.py`、`notes.py`、`assistant.py`、`config.py` 拆分，`routes.py` 负责汇总。输入和输出模型在 `app/schemas/` 按域声明，`app/schemas/api.py` 保留兼容导出。

| 能力 | 接口 | 阶段一行为 |
|---|---|---|
| 上传 | `POST /courses/{course_id}/materials` | 只保存文件并创建 `pending` 任务，返回资料和任务；执行器异步处理。支持可选 `Idempotency-Key` 请求头和 `allow_duplicate` 表单字段 |
| 查询任务 | `GET /jobs/{job_id}`、`GET /materials/{material_id}/latest-job` | 返回状态、阶段、进度、错误码、错误消息、尝试次数 |
| 重试 | `POST /materials/{material_id}/retry` | 仅失败任务可重试；新建待处理任务，原文件保留 |
| 配置状态 | `GET /config/status`、`GET /config/diagnostics`、`GET /config/provider-calls` | 区分未配置、已配置未验证及本进程最近一次连接结果；诊断返回本地路径、限制和脱敏的调用审计，不返回密钥 |
| 主动测试 | `POST /config/check/{deepseek\|embedding\|tavily}` | 用户主动触发单次最小调用；每服务至少间隔 1 分钟；可能产生费用，并记录状态/耗时/用量 |
| 课程移除 | `GET /courses/{course_id}/deletion-preview` → `DELETE /courses/{course_id}` → `POST /courses/{course_id}/restore` | 预览影响、删除前检查点、逻辑删除及恢复；有活动任务时拒绝 |
| 资料移除 | `GET /materials/{material_id}/deletion-preview` → `DELETE /materials/{material_id}` → `POST /materials/{material_id}/restore` | 同上；原文件、知识节点、用户笔记仍保留 |
| 恢复列表 | `GET /courses/deleted`、`GET /courses/{course_id}/deleted-materials` | 供本地 UI 显示可恢复对象 |

资料、笔记、任务等独立 ID 接口会校验所属课程仍有效；跨课程资料筛选不能用于另一课程答疑。答疑未传 `material_id` 时表示整门课程。

## 阶段三会话与知识整合接口

| 能力 | 接口 | 行为 |
|---|---|---|
| 持久会话 | `POST/GET /courses/{course_id}/conversations` | 会话只属于一个课程，切换课程不会带入旧历史 |
| 会话消息 | `GET /conversations/{id}/messages`、`POST /conversations/{id}/messages` | 保存有限历史窗口、学习目标、失败状态和证据映射；`idempotency_key` 防止重复消息 |
| 知识提案 | `GET /courses/{course_id}/knowledge-proposals`、`POST /knowledge-proposals/{id}/review` | 相似但名称不同的跨讲候选进入待确认状态，确认后写入变更记录 |
| 知识变更 | `GET /courses/{course_id}/knowledge-changes` | 查看新增、深化、来源补充和审核理由 |
| 笔记建议 | `GET/POST /notes/{id}/suggestions`、`POST /notes/{id}/suggestions/{suggestion_id}/review` | AI 只写建议；用户确认后才生成用户版本 |
| 反馈 | `POST/GET/PATCH /courses/{course_id}/feedback` | 答案、笔记、提案和来源反馈按目标去重并验证课程归属；PATCH 只更新人工处理状态和脱敏处理说明 |
| 术语说明 | `POST /courses/{course_id}/terms/explain` | 返回原文、常见译法、学科语境和出处不确定性；未配置可核验服务时保守返回，不伪造词源 |

答疑先检索课程内部资料；只有没有直接命中且策略允许时才调用联网搜索。回答来源按课件、网络补充、直接支持/相关支持分别标记。

## 阶段四备份接口

| 能力 | 接口 | 行为 |
|---|---|---|
| 导出完整包 | `POST /backups/export`（可选 `course_id`） | 不传课程时导出工作区；传 `course_id` 时只保留该课程及其关联资料、原文件和哈希清单；两者均不含 `.env` 和派生索引 |
| 导入预览 | `POST /backups/preview` | 隔离读取并校验版本、路径、数量、哈希、SQLite 完整性、数据库原文件引用，并返回当前同名文件冲突；不修改当前库 |
| 隔离恢复 | `POST /backups/restore`（multipart `file` + `confirmed=true`） | 仅在完成预览确认后恢复到本地隔离目录并记录状态，不替换当前数据 |
| 备份状态 | `GET /backups/{id}`、`GET /courses/{course_id}/backups` | 返回处理状态、清单摘要和脱敏错误 |

`GET /web-search/status` 继续兼容旧前端字段，但 Key 存在时状态是 `configured_untested`，不代表认证或搜索已成功。调用模型、联网和 Embedding 的实际结果需单独记录，不以配置状态替代联调验收。

## 阶段二解析与证据接口

| 能力 | 接口 | 行为 |
|---|---|---|
| 多格式上传 | `POST /courses/{course_id}/materials` | 接受 `.pptx`、`.pdf`、`.docx`；扩展名和容器结构都会校验，解析仍由本地持久化任务异步执行 |
| 能力与 OCR 状态 | `GET /config/capabilities`、`GET /ocr/status` | 返回后端真实支持的扩展名、上传/位置上限和 OCR 是否启用；前端据此显示限制 |
| 资料页面位置 | `GET /materials/{material_id}/pages` | 返回 `location_type`、`location_label`、`stable_location_key`、`extraction_method`、`confidence` 和告警；旧 `page_number` 字段继续保留 |
| 页面块级证据 | `GET /materials/{material_id}/pages/{page_number}/evidence` | 返回页面块、对象位置、提取方式、告警及当前有效关联笔记 |
| 资料来源覆盖 | `GET /materials/{material_id}/coverage` | 返回资料位置总数、已被有效来源引用的位置数、待检查位置数、位置明细和关联笔记 |
| 笔记来源定位 | `GET /notes/{note_id}/sources`、`GET /sources/{source_ref_id}` | 返回课件位置、来源状态和目标标签；来源状态不是 `active` 时，前端显示待核对提示 |
| 重新解析 | `POST /materials/{material_id}/reparse` | 沿用持久化任务；新解析版本成为活动页面，旧页面和来源保留并标记 `stale`，覆盖只统计活动版本 |
| 请求 OCR | `POST /materials/{material_id}/ocr` | 对活动 PDF 扫描候选页启动受限 OCR 任务；未启用或缺少 Tesseract/PyMuPDF 时返回明确的 `501`，不改变原有可浏览页面 |

扫描型 PDF 没有文字层时只记录 OCR 候选和待检查告警，不生成伪造的文本或来源。OCR 是独立的可选适配器，受 `NOTEBOOK_OCR_ENABLED`、`NOTEBOOK_OCR_MAX_PAGES` 和 `NOTEBOOK_OCR_LANGUAGE` 控制。

## 知识森林接口

以下地址均加 `/api/v1` 前缀。固定类型和请求字段见 [知识森林契约](superpowers/specs/2026-10-11-knowledge-forest-design.md)。

| 能力 | 接口 | 行为 |
| --- | --- | --- |
| 森林课程概览 | `GET /forest` | 返回轻量课程信息、学期/层级/状态/顺序/独立版本与笔记数量，不包含笔记正文 |
| 全局标题搜索 | `GET /forest/search?q=...` | 最多40条有效课程/笔记标题命中与稳定定位ID，过滤软删除资料，不返回正文 |
| 修改课程树信息 | `PATCH /forest/courses/{course_id}` | 提交 `expected_revision`，旧版本返回 409；不复用笔记本排序版本 |
| 藤蔓与候选 | `GET/POST /forest/relations` | 查询状态；显式手动连接两个不同课程的真实笔记 |
| 审核/移除关系 | `POST /forest/relations/{id}/review`、`DELETE /forest/relations/{id}` | 确认或拒绝 AI 候选；版本或来源变化时需复核；移除不改笔记正文 |
| 培养方案导入 | `POST /forest/curriculum-imports` | multipart `file`（PDF/DOCX）或 `text`，登记独立待处理任务，201 返回导入记录 |
| 导入列表/预览 | `GET /forest/curriculum-imports`、`GET /forest/curriculum-imports/{id}` | 显示解析模式、告警、可修改课程行、来源位置与错误 |
| 导入确认/重试 | `POST /forest/curriculum-imports/{id}/confirm`、`POST /forest/curriculum-imports/{id}/retry` | 确认 `{rows:[...]}` 才关联或建课；失败可重试，已有课程和笔记不删除 |
| 关系分析任务 | `POST /forest/courses/{course_id}/suggest-relations` | 手动重跑分析；资料生成笔记后也自动登记任务 |
| 最近课程关联任务 | `GET /forest/courses/{course_id}/latest-job` | 返回最近持久任务或 null；聚焦课程时显示自动任务错误和原任务重试入口 |
| 森林任务查询/重试 | `GET /forest/jobs/{id}`、`POST /forest/jobs/{id}/retry` | 持久任务状态和可读错误，失败重试由独立执行器领取 |

详细课程树现使用 `/forest/courses/{course_id}/tree` 多本目录；叶子携带真实 notebook_id、chapter 与 section 定位原笔记。关系两端需真实笔记 ID，不能拿概念 ID 代替同一概念在各讲的具体笔记。

2026-10-15 自动藤蔓更新：`CrossCourseRelationRead` 增加 `activation_mode=automatic/manual/null` 与 `evidence_fingerprint`，保留 `status=confirmed` 兼容。资料生成及笔记保存后，将受影响 Note ID、修订与来源指纹登记为持久 ForestJob；源集合每批不超过30，31个以上会连续分批处理，每批外课证据最多18。任务提交前重读当前端点、版本和真实引用；合法 AI 结果直接 confirmed/automatic，无需逐条确认，界面标记“自动关联”和“模型推断”。不承诺全量语义召回。

旧 pending 候选由独立任务重新校验后生效，迁移不调用模型；旧 confirmed 来源快照也会补验。来源或正文变化后旧关系隐藏并登记重分析，`GET` 不执行模型。`DELETE /forest/relations/{id}` 保留 rejected 记录，自动任务和重试不会复活；用户显式重新连接（POST同端点/类型）或对有效证据显式确认可恢复，过期关系确认返回409。手动连接仍为 manual。无模型时任务 failed 并返回明确错误，不生成虚假藤蔓；配置后从原任务重试。显式重新分析去重活动任务，读取仅限轻量标题及可验证片段。

上表“审核/移除关系”的 pending 审核描述是2026-10-11兼容接口，当前自动生效行为以本节更新为准；培养方案的预览确认及课程内知识提案不受此更改影响。
