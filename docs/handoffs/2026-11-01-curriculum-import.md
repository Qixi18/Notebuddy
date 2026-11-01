# 培养方案导入完善

基线：`67677dd`，沿用 `feat/overall-inspection`。功能验收后，用户已授权提交并推送该分支，不合并 main。任务：基于现有结构完善森林的培养方案导入。

## 行为

- 导入跟随设置中的标准/全程 AI 路线，也可单次选择。任务冻结路线、模型身份及源内容哈希；重试保持原路线。扫描 PDF 使用共享模型读页，DOCX 复用现有转页服务。
- 逐页、分批提取，每次 Worker 最多新增3步后让出；成功步骤保留。重试同时重置导入与作业状态，进度继续轮询，重复重试与重复确认拒绝。
- 课程行支持代码、学分、学时、必选修，以及学期、层级、先修和已有课程映射。不可编辑来源证据，模型数值须有对应表头依据。预览支持排除/恢复、重复提示、已知学分合计和与已确认方案对比。
- 确认使用事务和 profile revision 检查，保存新建课程 ID 与变更前后快照。已有课程的笔记、学习状态、顺序保留；迟发冲突回滚整批。
- 撤销先展示具体影响、再显式确认；创建检查点后重查属性版本和课程使用情况。只回收未被使用/修改的新建空课程，并恢复已有课程旧属性，revision 继续递增。后续修改、新增内容、改名、备份失败或重复撤销均不部分执行。

## 结构与边界

沿用 `CurriculumImport.rows_json` 保存课程附加字段，`ForestJob.source_snapshot_json` 保存路线和确认快照，`ProcessingStep` 保存成功步骤，无 schema 迁移。Notebook 正文、DocumentIR、资产和来源范围契约未变。

课程附加字段目前属于方案记录，未提升为全局课程字段。旧预览读取时可补版本，旧客户端确认关联课程时缺失版本必须刷新；旧已确认记录无撤销快照时不提供撤销。对比不删除未包含课程。该功能不判定毕业资格或学校完整培养规则。

## 文件

- 后端：`app/forest/curriculum.py`、新 `curriculum_processing.py`、`curriculum_reading.py`、`curriculum_confirmation.py`、`curriculum_revert.py`；`forest/jobs.py`、共享 `document_processing/llm_reader.py`、`api/v1/forest_imports.py`、`schemas/forest_imports.py`。
- 前端：`CurriculumImportPanel.tsx`、新 `curriculumReview.ts`、森林类型和样式、`api/forest.ts`、共享路线控件 `useProcessingRoute.tsx`。
- 回归：新增后端3个 curriculum 测试模块，新增前端 `curriculum-review.test.tsx` 并扩展 `forest-import.test.tsx`。
- 契约与操作：[API](../api.md)、[数据契约](../backend-data-contract.md)、[运行说明](../operations.md)；[设计](../superpowers/specs/2026-11-01-curriculum-import-design.md)、[计划](../superpowers/plans/2026-11-01-curriculum-import.md)。

## 验证

定向检查：后端29项、前端8项通过。浏览器使用合成数据和实际组件，验证默认全程 AI、课程明细、390px窄屏、排除后恢复、确认、撤销影响和撤销完成；无控制台错误。临时验证页面和截图位于被忽略的 `apps/web/output/tree-inspection/`，不提交。

最终官方入口 `pwsh -NoProfile -File .\scripts\test.ps1` 退出码0：Ruff通过，后端435通过/4跳过，前端52 Node +410 Vitest（共462项）通过，Web和桌面构建通过。`git diff --check`通过。日志：`.runtime/logs/curriculum-reviewed-final-check.log`、`.runtime/logs/test-20261101-145936-37616.log`。所有测试使用隔离库，禁用付费服务；未验证真实模型识别质量或对用户资料执行导入/撤销。已有可选真实OCR/私人课件测试跳过，构建保留既有 bundle 大小提示。

## 执行选择

1. 在现有功能分支继续，不另建 worktree；实现阶段保留工作区，验收后按用户授权统一提交推送。
2. 复用现有 JSON 与步骤表，不新增数据库字段。代价：课程代码/学分等仅在方案记录中使用；全局课程字段扩展需要另行设计。

独立只读审查发现跨批次标题上下文、跨页续表、代码列证据三项问题，以及旧方案补代码的差异匹配问题。均先由回归复现失败，再修复；对应29后端/8前端定向检查与最终完整检查通过。续表沿用前一表头时显示核对告警，明确标签也可作为元数据证据。无未处理的已知 Critical/Important 问题。真实模型识别、Office转换质量和大型资料库检查点耗时未实测；此前既有解析器/服务行为与全局课程元数据扩展不在本次改动范围。
