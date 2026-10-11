# API 契约

## 课程笔记本（2026-10-08）

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
