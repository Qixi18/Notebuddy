# ADR-0001：Notebook 正文权威源与资料处理边界

- 日期：2026-10-30
- 状态：Proposed（待协作者审核；不表示本轮获批业务架构变更）
- 记录时本地基线：`0777d0ef6ba6c44d2e498238d605631ee907c6b3`
- Fetch 时远端基线：`4759ff50c3100894af47dfca72476fe1c14e9e4a`
- 发起原因：协作文档仍描述旧 Note 正文及逐页解析为当前主路径，容易引入重复正文存储或重复解析。

## 现状与提议

源码当前以 `Notebook.document_json` 保存用户可编辑正文，并用 `document_revision`、不可变文档版本及 CAS 写路径保护更新。原始文件经 Asset/Notebook 资源台账和持久任务进入 Document Processing；版本化 DocumentIR/ParseRun 保存解析结果、来源位置与质量状态。生成任务保存输入快照，经结构、公式及来源校验后，以基准 revision 合并写入正文。NotebookSection、检索块、森林目录是从权威数据构建的派生数据。旧 Note、NoteRevision、NotebookGenerationCandidate 仍可能承担迁移、兼容或历史审计职责，不等于当前正文入口。

本 ADR 提议将上述现状作为协作文档的共同基线。替代方案是继续将旧 `Note.content_markdown` 或每页 ParsedDocument 模型描述为当前正文链；这与当前代码不符。

## 影响和约束

- 影响模块：Document Processing、生成 Worker、Notebook 编辑器、检索、知识森林、Agent、兼容 API 与数据迁移文档。
- 正文读写/API：沿用 Notebook document 路由及 `document_revision` 冲突语义；不得另建正文源。
- 数据库/迁移：本 ADR 不要求模式变更或删除历史表；任何迁移需另立提案并隔离验证。
- 其他协作者：森林与 Agent 从服务端 Notebook/派生索引及限定范围证据读取；不自行重复解析资料或信任浏览器临时状态。
- 兼容/恢复：保留历史 Note、来源关联、版本和备份可读性；删除兼容数据需要独立数据迁移、回滚及恢复方案。

## 验证和风险

需要 API/服务测试覆盖 revision 冲突、失败不部分写入、上传幂等与重试、来源归属、索引重建；真实材料和浏览器验证另行记录。本轮文档更新不代表上述行为全部验收通过。尚未解决风险包括真实材料质量、历史库迁移恢复覆盖和外部 API 兼容调用方。

- 审查者：待指定
- 接受时间：未接受
