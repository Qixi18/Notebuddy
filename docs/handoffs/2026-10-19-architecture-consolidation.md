# 2026-10-19 架构收敛交接

## 目标与分支

- 分支：`feature/architecture-consolidation`，从本地与远端一致的 `main` (`2a6d92f`) 创建。
- 保留已有的 `apps/web/vite.config.ts` 修改及两个未跟踪设计文档，不纳入本任务。

## 代码处理

- 会话消息、证据与会话加载共用 `app/services/conversations.py`；传统问答与 Agent SSE 保留各自调用及失败流程。
- 搜索缓存、供应商审计、来源审核与保存共用 `app/web_search/service.py`；搜索词仍由各调用方确定。
- 来源转换集中于 `app/services/assistant_sources.py`，术语原文查询集中于 `app/services/terms.py`。
- Agent 只读工具、工具返回契约、笔记小节编辑算法分离；修正笔记建议工具名称与时间线名称不一致。
- 答疑页与答疑坞共用 Markdown 和来源渲染；设置状态与操作移入 `useSettingsDraft`。
- 森林相关 ORM 定义移入 `app/db/forest_models.py`，`app.db.models` 保留兼容导出，未改表结构或迁移。
- 本地执行器连续处理三个资料任务后尝试领取森林任务；密钥写入文档改为与现有本地模式及测试一致。

## 验证与边界

- `apps/backend`: `uv run ruff check app tests` 通过；`uv run pytest -q` 为 234 passed、1 skipped。
- `apps/web`: `npm test` 为 33 个 Node 测试及 129 个 Vitest 测试通过；`npm run build` 通过，保留原有大 chunk 警告。
- 新增搜索缓存/失败审计、持续资料队列下森林任务公平性，以及消息 Markdown/来源入口测试。
- 本次未运行真实模型、Tavily、真实课件或浏览器完整交互验收；自动化结果不能替代这些验收。
- 用户已确认本任务提交使用 `AGENTS.md` 指定的 `mawenzhe33` 身份；提交与远端交付状态以 Git 实际记录为准。
