# 检索与答疑评测基线

## 检索模式

`app.retrieval.service.retrieve` 在 Embedding 已配置时使用向量分数与关键词分数混合；未配置时明确使用关键词回退。`retrieval.rerank` 只做可解释的词项加权，不把命中直接当成事实。

`retrieval.index.rebuild_course_index` 可以从活动页面块重建派生块；重建失败不会删除 SQLite 页面、来源或笔记。`retrieval.evaluation.evaluate` 接受人工标注的 `RetrievalExample`，输出命中率、MRR、页码和当前检索模式。

在 Windows PowerShell 中，从仓库根目录使用项目环境重建：`& .\apps\backend\.venv-document\Scripts\python.exe -m app.retrieval.index --course-id <课程 ID>`，或增加 `--material-id <资料 ID>` 只重建一份资料。仅对隔离数据目录执行重建评估，避免误改用户数据。

## 推荐人工集

至少包含：课程内单讲问题、跨讲问题、课程无证据问题、同词异义问题、同名不同课程问题。记录问题、期望位置、实际位置、分数来源、耗时和是否直接支持。没有真实标注样本时，报告只能标记为“基线工具已实现”，不能写成语义质量验收通过。

## 答疑编排

`app.ai.orchestrator.run_answer` 使用有限会话历史，先检索当前课程，再在无直接命中且策略允许时调用 Tavily。网络结果经过 HTTPS 和来源类型检查，并以不可信引用文本传给模型。模型失败时保存失败状态并返回课程/网络分层摘录；没有依据时明确显示无证据。
