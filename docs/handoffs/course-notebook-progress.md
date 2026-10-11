# 课程笔记本执行记录

分支：`feat/course-notebook`；基线：`97eb151`；用户已授权检查通过后合并 main，不推送。

| 任务 | 状态 | 证据 / 待办 |
| --- | --- | --- |
| 1 基线与迁移 | 已实现并验证 | Web 构建通过；后端初始 14 failed / 89 passed / 1 skipped。旧测试与现有软删除、建议保护、任务唯一性、迁移 head、解析告警发生偏差；另有真实的笔记重复插入、关系名称匹配、课程更新字段校验问题。 |
| 2 按讲生成 | 已实现并验证 | 同概念不同正文、重试稳定身份、相似提案不阻断阅读 |
| 3 API 与顺序 | 已实现并验证 | 版本冲突、课程隔离、历史分组、来源归属 |
| 4 阅读器 | 已实现并验证 | 书架、章节/整本、准确小节、编辑历史 |
| 5 入口联动 | 已实现并验证 | 各讲叶子、覆盖跳转、查询参数草稿保护 |
| 6 验收与合并 | 完成 | 1972aa3 已快进合并本地 main；合并后后端 115 passed/1 skipped、Ruff 与前端 12 项/构建再次通过；本记录在任务分支补充后合并 |

原始本地 Word / 需求文件不随手暂存。实际课程、真实 AI、专项知识树视觉不在本轮验收结论中。

裁定：数据模型、生成、API 相互依赖，任务 1–3 合并为后端提交；任务 4–5 为前端提交。仍按用例观察 RED→GREEN。旧测试更新遵循已有软删除和建议机制，未恢复自动覆盖。浏览器备用 Playwright CLI，内置浏览器沙箱启动失败。

Task 1–3: complete (commit 276062b); Task 4–5: complete (commit 703f52d); Task 6: complete (review fixes 1972aa3, local main verified). Final backend full suite: 115 passed, 1 skipped (real deck fixture absent), 1 upstream deprecation warning; Ruff passed. Web: 4 navigation + 8 React tests passed, production build passed. No push.

Final: fixed delayed save/reload/suggestion draft interference — note-editor.test.tsx / note-suggestion.test.tsx RED→GREEN, React suite 8/8.
Final: fixed pending chapter outline refresh — notebook-refresh.test.tsx RED→GREEN, React suite 8/8.
Final: fixed cross-material source page reset — workspace-source.test.tsx RED→GREEN, React suite 8/8; browser second lecture/page2 verified.
Final: fixed historical web source scope — test_historical_web_sources_follow_actual_note_materials RED→GREEN, backend suite 115 passed / 1 skipped.
Final: fixed shared-concept lecture filter and source details — knowledge-filter.test.tsx RED→GREEN, React suite 8/8.
Final: fixed whole-book historical sections — notebook-refresh.test.tsx RED→GREEN, React suite 8/8.
Final: minor (deferred): none.

审查排除项逐项裁定（沿用已确认范围）：
- Final: Ruling: 选页补生成、难点、桌宠/问答上下文、知识树专项美术 — 后续任务；本轮方案 A 聚焦笔记组织阅读 — 若误判，首期整体功能仍不完整。
- Final: Ruling: 多文件合讲、人工无来源章节、拖拽排版 — 设计明确排除 — 若误判，目前每资料一章且无法提供这些编辑方式。
- Final: Ruling: 真实课件/AI、性能、10 条编辑/30 条来源正式验收 — 当前无足够证据，只报告本地合成验证 — 若误判，真实使用质量仍未知。
- Final: Ruling: Electron 安装交付、旧 PPT/DOC、OCR/复杂公式 — 本轮未承诺交付 — 若误判，安装与复杂材料支持仍需后续完成。
