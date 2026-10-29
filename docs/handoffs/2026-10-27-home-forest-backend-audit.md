# 首页与知识森林后端检查记录

检查基线：`feat/home-knowledge-forest`，HEAD `00c6720`，包含当前工作区尚未提交的正文同步与生长动画。此记录汇总现状、复现证据和开发约束；本轮没有修改产品代码、数据库或调用真实模型。

## 1. 当前已有的可复用结构

| 层次 | 当前实现 | 前端对应 |
| --- | --- | --- |
| 课程与学习配置 | Course + ForestCourseProfile | 一门课程一棵树；首页最多三门 learning 课程 |
| 笔记本 | Notebook；course_id 可空，支持未分类笔记 | 一条主枝；tree_slot 保持稳定 |
| 来源文件 | NotebookAsset / Asset；文档解析仍经过 Material / MaterialPage / PageBlock | 资料与解析状态，不直接等同树叶 |
| 正文 | Notebook.document_json + document_revision + NotebookDocumentRevision | 富文本编辑、并发保护和历史 |
| 知识小节 | Note + document_block_id + tree_slot + revision_number | 稳定叶子及精确打开位置 |
| 证据 | SourceRef / note_source_refs / NoteSourceMapping | 来源回查与关系校验 |
| 知识概念 | KnowledgeNode / KnowledgeEdge | 课程概念图；不能用概念 ID 代替笔记小节 ID |
| 跨课关系 | CrossCourseRelation + 来源指纹及双方修订 | 可核验的跨课藤蔓 |
| 笔记本关系 | NotebookRelation | 笔记本之间的手动链接，与知识点藤蔓语义不同 |
| 异步工作 | ProcessingJob / AssetProcessingJob / NotebookGenerationJob / ForestJob | 解析、图片 OCR、正文生成、跨课关系四类任务 |

已有读取接口：`GET /forest`、`GET /forest/courses/{course_id}/tree`、`GET /forest/search`、`GET /forest/relations`。首页和森林已共享 `useTreeDirectories` 与 `useAutomaticVines`，无需另造业务存储。

## 2. 数据链路检查

1. `workers/material_worker.py:139` 仍调用 `extract_material_knowledge()`；`knowledge/extractor.py:124` 按解析位置创建/更新 Note，并建立来源。大文件依然会逐页调用提取逻辑。
2. `services/notebook_generation_inputs.py:194` 协调上传批次，等解析任务完成后创建正文生成任务；`workers/notebook_generation_worker.py:192` 直接将新增节点追加到 Notebook.document_json。
3. 第二条链路没有调用正文小节同步，且使用 `dump_document` 而非保留 `section_revisions` 的编码器。生成完成不是“正文、树叶与证据已一致”的保证。
4. 手动保存课程笔记会调用 `notes/notebook_sections.py:135` 的 `sync_sections()`；当前新增 H2 被当作用户小节。此函数具有用户保存的来源和锁定语义，不能原样用于 AI 自动追加。
5. `api/v1/generation.py:322` 的候选应用也直接写正文；统一入口需要覆盖自动追加和候选应用两种写入模式。

## 3. 纯内存复现结果

复现脚本在本机忽略目录 `data/diagnostics/forest_contract_audit_20261027.py`，输出 `forest-contract-audit-20261027.json`。使用 SQLite 内存库和合成文本；正文生成函数替换为固定返回值，不读取业务数据库、不执行真实模型调用。

| 情况 | 复现结果 | 对首页/森林的影响 |
| --- | --- | --- |
| 已有 1 个小节后 AI 追加一个新 H2 | 任务 completed、正文 revision=1、新标题已存，但 Note 仍只有 1 条 | 新正文不立即成为树叶 |
| 同一追加过程 | 原有 section_revisions 不再保存在文档包装中 | 小节并发基线不能稳定跨越生成写入 |
| 随后手动保存上述正文 | 新增小节才成为 Note，origin=user、user_locked=true、来源引用数=0 | AI 内容被标为用户小节；无法直接满足跨课关系证据规则 |
| 将笔记本设为已删除状态 | 课程 summary_notes=1、tree_notes=0，森林搜索仍命中 1 条 | 统计、目录与搜索口径不一致 |
| 调用 move_notebook 将笔记本从 A 移到 B | Notebook.course_id=B，但 Material.course_id=A、Note.course_id=A；A 统计 1/树叶 0，B 统计 0/树叶 0 | 归属移动后叶子不跟随课程树 |

删除可见性问题来自 `forest/service.py:96` 的谓词未校验所属 Notebook 的存在、课程一致性和 deleted_at。`forest/relation_candidates.py:16` 又维护了另一套类似过滤，需要一并统一。

移动问题来自 `api/v1/notebook.py:559` 只更新 Notebook 归属。绑定入口 `:378` 也没有建立小节投影和补齐已解析资料的课程关联；这一点为静态代码检查，未在本轮另做绑定复现。

## 4. 状态与性能方面的开发约束

- Material processing completed 与 Notebook generation completed 是不同阶段。当前 `useTreeDirectories.ts:60` 依据资料章节 pending/processing 决定是否轮询，不能覆盖资料已完成但正文仍生成的全部生命周期。
- `material_worker.py:135` 在整段知识提取前设置 progress=96；这不是准确剩余时间。首页应显示阶段、已完成项和可打开的结果，不据此承诺倒计时。
- 绑定课程的文档可能先经历逐页知识提取，再经历批次正文生成。应在选择主生成路径后评估重复模型工作；本轮没有测量其额外耗时。
- 现有 `GET /forest` 返回学习配置、资料数与知识点数，没有课程内容版本、批次任务概览或增量变更游标。profile.revision 只是森林课程配置版本，不能充当正文/树目录版本。
- 跨课藤蔓当前要求双方真实来源、修订与证据指纹。新富文本小节或图片 OCR 内容没有满足该规则前，应标明依据尚不足，不能假装关联分析失败或伪造 SourceRef。
- 逐课程读取目录、逐关系核验来源会产生多次查询。这是代码级性能风险，未做大规模查询基准；可在正确性修复后增加批量读取和预加载。

## 5. 首页和森林开发时应保持的约束

- 课程 ID 对应树、笔记本 ID 对应枝、小节 Note.id 对应叶。名称改变不改变 ID；同名小节不自动合并；block_id 负责定位正文，tree_slot 负责绘制位置。
- 笔记本正文与小节投影必须在同一事务中提交，成功后再让前端领取动画；失败、草稿与未应用候选不长出正式叶片。
- 同一可见性口径应服务统计、目录、搜索、续读、关系候选及关系展示。未绑定历史 Note 可以保留兼容阅读，但应区分“历史未归档知识点”与“可画在树上的叶子”。
- 课程归属变更需要统一处理资料、Note、课程概念、检索和旧关系失效。不要仅修改 Notebook.course_id，也不要按标题重新建立 ID。
- 首页只选最多三门 learning 课程；森林显示全部有效课程。两者读取同一套后端树结构，布局、相机、临时选择和动画播放状态留在前端。
- 跨课关系任务失败不能把已完成的笔记显示为生成失败；恢复、移动与重新绑定默认刷新视图基线，避免被当作新内容生长。

详细方案尚待选择：可在两条现有写入路径逐处补同步，也可抽取共享的正文提交/小节投影服务供各入口调用。推荐共享服务，能够覆盖后续 AI 编辑、恢复和迁移入口，同时复用现有 Note ID 和树素材。
