# 当前架构说明

本页描述 `feat/debug-integration` 当前实现；跨协作者共同入口是根目录 [AGENTS.md](../AGENTS.md)，详细契约见 [backend-data-contract.md](backend-data-contract.md)。历史设计只作为历史证据，不可覆盖当前代码事实。

## 正文与来源

```text
Notebook / Asset
  → 持久上传与处理任务
  → Document Processing / DocumentParseRun / DocumentIR
  → 生成快照与质量门禁
  → Notebook.document_json（唯一正式正文，document_revision）
  → 编辑器、章节投影、检索派生索引、森林导航、范围化 Agent 读取
```

Notebook 正文由 `apps/backend/app/notes/store.py` 的统一写入逻辑保存，并维护 revision、历史快照与章节索引。`apps/backend/app/notes/index.py` 中的 `NotebookSection` 是可重建目录/文本投影，不是第二正文源。`DocumentIR` 与 ParseRun 是源文件解析的版本化结构和质量信息；检索块、森林目录为派生数据。旧 `Note.content_markdown`、NoteRevision 与 `NotebookGenerationCandidate` 仍有迁移、兼容或历史含义，不应据此恢复旧正文链或删除历史资料。

## 请求与后台任务

`apps/backend/app/api/v1/routes.py` 注册 config、courses、materials、jobs、knowledge、notebook、generation、assistant、conversations、agent、feedback、backup、terms、forest、forest_imports、quiz 路由。API 校验范围及输入，服务层处理业务，持久任务由 `apps/backend/app/workers/runner.py` 运行。缺少 Worker 时，异步解析/生成可滞留队列。

Notebook 上传登记 Asset/资源归属和持久任务；批次完成后由后台协调解析与生成输入。解析结果通过 Asset 关联当前/历史 ParseRun。生成 Worker 对解析结果执行质量检查与来源校验，使用任务基准 revision 与当前正文合并；revision 冲突应保留用户修改。上传后初始/增量生成允许在门禁后写正文；Agent 对已有正文的主动改动通过 `NotebookEditSuggestion` 或受控操作，并核对基准 revision。

## Web 与知识森林

前端路由入口 `apps/web/src/App.tsx`。Notebook 页面在 `features/notebook-editor` 和 `features/notebook-workspace`，通过 API 读写 JSON 文档。资料页中的旧路径有 `LegacyMaterialsRedirect`，旧 `MaterialsPage.tsx` 仍在仓库，不能仅据文件存在推断它是当前主路由。知识森林从课程、Notebook/Section 和关系数据构建展示及定位，不复制正文。Agent 通过服务端工具读取 Notebook 与证据，并按课程/Notebook 范围校验。

具体请求、兼容接口和验证级别见 [API 契约](api.md)；DocumentIR 版本关系见 [解析说明](parsing.md)。

## 本地数据与运行

默认数据根目录是仓库 `data/`，可由 `NOTEBOOK_DATA_DIR` 覆盖；数据库和上传原件不进入 Git。启动入口、迁移副作用、端口和测试隔离以 [README](../README.md)、[operations](operations.md) 和脚本源码为准。`dev.ps1` 启动前会执行数据库迁移，因此只允许在用户已选择的本地开发数据目录使用；本轮不操作真实库。

## 架构决策

当前基线记录在 [ADR-0001](architecture-decisions/ADR-0001-notebook-document-source-of-truth.md)，状态 Proposed，未获审核。未来全局变化需先记录提案、同步 README 公告、数据契约、API、测试及 Agent 影响；不得把历史计划当作实施依据。
