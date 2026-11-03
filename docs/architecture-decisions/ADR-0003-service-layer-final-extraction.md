# ADR-0003：后端路由业务职责下沉

- **状态：Proposed**（本地实现已完成，待技术把关者审查）
- **日期：**2026-11-03
- **基线：**`feat/overall-inspection`，`10486d03c94ef188aec8b3ae96c3fae6be1617c9`
- **范围：**Notebook 文档/历史/生命周期/资源、Material 兼容读取、Asset 处理查询、上传批次、共享资源范围及 Service 错误边界。

## 背景与证据

拆分路由文件后，若干端点仍直接执行 ORM 查询、DocumentIR 读取和响应数据聚合；个别路由自行把 `ApplicationError` 转成 `HTTPException`，且 `services/quiz.py` 直接依赖 FastAPI。项目已有全局 `ApplicationError` 处理器、`notebook_document.py` 正文存储用例和 `document_reads.py` DocumentIR 读取入口。本次采用用户审阅的 2026-11-03 架构验收建议，延续既有服务边界，不引入 Repository/UoW，也不增加数据库字段或迁移。

## 决策

1. Router 处理 HTTP 输入/输出、上传文件读取和 `FileResponse`；查询、归属校验、业务组装和事务交由应用 Service。
2. Notebook 正文读取/保存、来源、章节及历史读写统一由 `services/notebook_document.py` 提供用例；底层正式正文写入仍只经 `notes/store.py` 的 `write_document`。
3. DocumentIR 的旧 Material 页面/证据响应由 `services/document_reads.py` 在现有 ParseRun/IR 上投影，保留兼容端点和字段，不再在 Router 建第二条读取路径。
4. Material 聚合查询集中在 `services/material_reads.py`；Notebook 资源、生命周期、处理任务和上传批次查询复用对应既有 Service。
5. 共用资源范围校验由 `services/resource_scopes.py` 执行。Service 抛出框架无关的 `ApplicationError`，由 `app/main.py` 的全局处理器映射 HTTP 响应；业务异常在应用服务边界转成 `ApplicationError`。
6. Notebook order 与 reading-position 服务接收普通字段，不接收 API 请求 schema。数据库访问仍可使用 SQLAlchemy Session。

## 兼容性、数据与回滚

- 所有现有 HTTP 方法、路径、状态码声明、请求模型和响应模型保持原样；旧 `/materials/.../pages` 与证据端点继续存在，无当前解析版本时页面列表仍返回空列表。
- `Notebook.document_json`、revision/CAS、历史快照、附件 pin/归属语义及 DocumentIR 当前 ParseRun 选择规则不变。
- 不新增迁移、不改已发布迁移、不读取或修改真实用户数据库，不触发付费模型调用。
- 实现可通过回退本 ADR 对应的应用 Service 与 Router 改动撤销；无需数据回滚。工作区原有三份文档未提交修改不属于本次回滚范围。

## 验证

- 新增边界回归断言：Service 不导入 FastAPI；指定 Router 不直接查询/提交 ORM；目标 HTTP 路由不再逐个映射 `ApplicationError`。
- 保持 Notebook 路由契约快照作为路径、方法和状态码验收。
- `pwsh -NoProfile -File .\scripts\test.ps1`：后端 Ruff 通过，pytest 572 passed/4 skipped/2 warnings；Web Vitest 80 files passed、5 failed（404 passed/22 failed）。因 Web 测试失败后官方脚本停止，手动执行 Web `npm run build` 与 Desktop `npm run build:main` 均通过；详细失败文件见 [验收快照](../acceptance.md)。
- 不包含真实 PDF/图片解析质量、浏览器人工验收、外部模型或账单验收。

## 影响与审查

本项是跨 Notebook、Materials、资源和错误处理模块的架构调整。技术把关者审查前本 ADR 保持 Proposed，不代表整体后端架构已获接受。当前改动未提交、未推送。
