# 历史方案说明

本文记录的是早期 KnowledgeProposal、NoteSuggestion 与 Note 数据模型，需按接口分别看待：`GET /courses/{course_id}/knowledge-proposals`、`POST /knowledge-proposals/{proposal_id}/review` 仍由 knowledge 路由提供；前端仍调用旧 Note suggestion 列表/审核路径，但本轮在 `apps/backend/app/api/v1/` 未找到对应后端路由，属于未解决的前后端契约差异，不能据此宣称该旧流程当前可用。它们都不是 Notebook 正文的权威实现。当前 Notebook 正文和编辑建议以 [backend-data-contract.md](backend-data-contract.md)、[architecture.md](architecture.md) 及 `apps/backend/app/api/v1/notebook.py` 为准；森林关系语义以当前 forest 路由、服务和测试为准。

# 阶段三：知识整合与证据规则

## 数据边界

SQLite 中的页面、块、来源、笔记和知识关系是权威数据；`retrieval_chunks` 只保存可重建的派生检索数据。所有查询都带 `course_id`，并再次检查资料和页面归属。

## 候选流程

1. `app.knowledge.matcher` 对同课程节点进行名称规范化、字符序列和术语重合度比较。
2. 名称完全一致的候选可标记为 `repeat/auto_applied`，只补充来源；相似但名称不同的候选标记为 `deepen/pending`，不能自动合并。
3. `KnowledgeProposal` 保存候选、置信度、理由、来源 ID、差异和状态。用户通过 `POST /api/v1/knowledge-proposals/{id}/review` 确认或拒绝。
4. 确认会生成 `KnowledgeChange`，并将来源挂到目标节点；拒绝只记录审核结果。
5. 关系通过 `knowledge.relations.add_relation` 建立，检查课程一致、自环、重复边和先修/层级循环。

用户已经编辑的笔记继续由 `Note.user_locked` 和版本号保护。AI 片段进入 `NoteSuggestion`，只有确认后才调用用户版本更新流程。

## 前端核对

知识树详情显示待确认提案；笔记来源侧栏显示待确认 AI 建议；答疑消息展示已保存的证据映射。来源卡片继续区分课件、网络补充和待核对状态。
