# ADR-0002：Notebook 核心架构整改路线

- 状态：**Proposed**（待协作者审核；不能作为已批准架构或已完成实现）
- 日期：2026-11-01
- 审查基线：`origin/feat/overall-inspection` @ `67677dd8771f2fe756d2f29a986102a64655a730`
- 来源：用户要求按 `2026-11-01-Notebuddy-Codex-核心架构整改开发规划.md` 执行

## 背景

现有答疑通过 Agent 工具循环生成并流式发送正文，旧 Note 写回入口仍出现在前端和工具定义中；未分类 Notebook 的会话仍受课程 ID 契约限制。文档处理已有 `standard`/`llm` 两条路径、调用审计和阶段检查点，但尚未确认存在统一的视觉模型能力预检与按 Asset 原子预留的 CNY 预算闸门。课程和未分类 Notebook 页面也分别维护编排。

## 提议

按小批次逐步达成以下业务契约：

1. 答疑以当前已保存 `Notebook.document_json` revision 为第一来源，基于 Notebook 关联的有效 DocumentIR/ParseRun 逐项核验证据；存在实质冲突或关键证据不足时复用现有 WebSearch。核验结束前仅发送状态事件，不发送正文 delta；最终回答、证据和消息持久化需绑定同一上下文快照。
2. 本轮 Agent 对 Notebook 正文只读。隐藏旧 NoteSuggestion 写回 UI，禁用 `propose_notebook_edits` 新建路径，保留兼容表、迁移及历史读取能力。
3. 会话以 `notebook_id` 表达 Notebook 范围；课程归属可以为空，但空课程只允许 Notebook 级读取。历史 `scope='note'` 会话须有显式、安全的兼容读取规则，不得用最近课程伪造归属。
4. 视觉识别配置与文本模型配置分开，并在付费读页前验证图像输入能力。每个原始 Asset 从解析到对应 Notebook 正文生成的模型调用合计不得超过 **10.00 CNY**；解析、规划、正文生成、格式修复、重试及能够归因到该文件的自动关系调用都纳入同一预算。预算不足时终止该文件后续收费步骤，不自动切路线或换模型。只有能建立保守最坏费用上界时才准许调用；预算不足或费用不明时 fail closed。
5. 稳定 A/B 契约后，让课程和未分类 Notebook 两条历史路由共享同一个 Workspace。其后再渐进拆分 Notebook API/服务层。

## 批次与影响范围

- A1/A2：AssistantPage、AssistantDock、会话 schemas/API/model、Agent 循环/工具、检索、Web 证据、SSE 和相关测试。
- B1/B2：配置、provider client、Document Processing、generation/worker、调用审计/预算数据模型、迁移、API/UI 状态和 Fake Provider 测试。
- C1/C2：Notebook 页面、共享 editor/save、上传/生成/历史/资源 hooks 与旧 URL 路由。
- D：Notebook API/service 分层和导入方向。

新增数据迁移仅允许增加新 revision，不允许修改已发布 Alembic 历史；数据库验证使用隔离目录，不连接 `data/notebook.sqlite3`。Web Search 沿用既有服务及限流，文件预算与普通对话搜索费用分开。

## 兼容、风险与回滚

- 保留既有课程/未分类 URL、Notebook 正文 JSON、revision/CAS、历史、来源映射、ParseRun、任务检查点和既有迁移。
- 旧会话须可读；若无法无歧义解析旧 note 标识，应以明确限制结束，不能猜测映射。
- SSE 变化可能改变客户端事件顺序和断线持久化；需先更新 schema/types、契约与回归测试，再切流。
- 预算实现依赖准确的供应商价格、图片计价、汇率和请求上界；价格未知或 usage 状态不明不得自动退款/重试。
- 每批保持独立提交、测试和回滚边界。失败时回退该批代码/新迁移前，先验证旧数据可读取；禁止删除或重写历史迁移。

## 验证要求

按规划中的 AI-01…AI-11、BUD-01…BUD-07、NB-01…NB-04、ARC-01 建立隔离 Mock/Fake Provider 测试。真实供应商、真实材料、浏览器和价格账单对照作为单独证据，不以自动测试替代。每批记录确切命令、退出码、用例计数、失败和跳过项。

## 审查状态

本条目仅记录用户给定计划及基线调查；待协作者审查后方可改为 Accepted。实施期间若证据迫使业务契约改变，先更新 Proposed ADR 和兼容方案，再继续对应批次。

Notebook 会话兼容与 SQLite 迁移细节见 [A1 会话迁移设计](../notebook-assistant-session-migration-design.md)；原设计已完成只读协作者审查，本次迁移实现仍待实现评审，整体仍为 Proposed。

## 实施记录（A1 工作区，待实现评审）

已在 `feat/overall-inspection` 工作区加入迁移 `f2b7d9a1406c`、Notebook 专属会话 CRUD、旧 Note ID 冲突拒绝、只读工具注册和前端旧 Note/正文写回入口清理。Notebook 会话问答暂时返回 409；只有 A2 的核验服务完成后才能开放。针对性自动测试与前端构建已通过，完整仓库回归和本次协作者实现评审尚未结束。此记录不改变本 ADR 的 Proposed 状态，也不代表 A1 完成验收。
