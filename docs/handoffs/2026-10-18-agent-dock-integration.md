# Agent 悬浮坞合并到课程助手重构分支

- 目标分支：`feature/course-assistant-redesign`，合并前 HEAD `9f9c4f5`。
- 来源：`origin/feature/agent-dock`，合并时 HEAD `e0857be`。
- 两个分支从 `7814f87` 分叉；采用保留双方历史的合并提交。

## 目录适配

- 答疑侧栏继续位于 `apps/web/src/features/assistant/AssistantDock.tsx`，保留本地三栏页面和初始快捷提示，接入远程的 Agent 步骤、流式回答与建议卡。
- 笔记正文阅读器继续位于 `apps/web/src/features/notes/NoteSectionReader.tsx`，接入远程的原位建议审查、部分采纳与历史版本恢复；`apps/web/src/pages/NotesPage.tsx` 保持旧链接重定向入口。
- 新增的 Agent API、后端工具与测试按现有 `api/`、`ai/`、`features/assistant/` 目录组织。原分支的设计计划保留为历史记录，其中提到的旧组件路径以本节为准。

## 验证

- Web：`npm ci`、`npm run build`、`npm test`，构建通过；33 个导航测试和 127 个 Vitest 测试通过。
- 后端：`uv sync --locked`、`uv run ruff check app tests`、`uv run pytest -q`，Ruff 通过；231 个测试通过、1 个跳过。
- 未执行真实模型调用、真实课件质量验收和完整浏览器视觉检查。以上测试使用隔离检出的工作树，不触碰用户本地数据。
