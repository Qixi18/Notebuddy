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

Notebook 会话兼容与 SQLite 迁移细节见 [A1 会话迁移设计](../notebook-assistant-session-migration-design.md)。A1、A2 与 B1 均完成各自的只读协作者实现审查；整体 ADR 仍为 Proposed，因为 B2、C1/C2、D 尚未实现和验收。

## 实施记录（本地工作树）

### A1

已实现并在 `feat/overall-inspection` 推送提交 `0b0c033`：迁移 `f2b7d9a1406c`、Notebook 会话 CRUD、旧 Note ID 冲突拒绝、只读正文入口和旧写回工具关闭。独立评审未发现阻断问题；完整 `scripts/test.ps1` 后端 439 passed / 4 skipped，Web navigation 52、Vitest 411 通过，Web/Desktop 构建通过。未做真实模型/材料及浏览器人工验收。

### A2

本地未提交工作树新增 `app.ai.notebook_qa` 固定核验服务和迁移 `a7c4d2e91b60`。课程和未分类 Notebook 两类会话均按绑定 Notebook 和 revision 校验；DocumentIR 查询限制到该 Notebook 当前 completed ParseRun 和有效 owner 资产。流水线在服务端缓冲初稿，逐主张审查、检查初稿覆盖、按需使用现有 WebSearch、审查网页来源、生成最终答案，再由 AnswerGate 检查证据 ID，并独立检查最终答案主张覆盖；任一结构无效或答案冲突即停止发布。仅在服务端持久化核验记录；对外消息过滤内部核验字段。普通 JSON 与 SSE 两入口共用该服务和来源映射函数；SSE 在持久化完整答案后输出正文 delta，断开会将消息标记 aborted。

独立协作者复审确认 A2 两项 P1（来源错误归因、最终答案覆盖不完整）已关闭，未发现剩余阻断。A2 最终完整 `pwsh -NoProfile -File .\scripts\test.ps1` 退出码 0：Ruff 通过；后端 448 passed / 4 skipped / 2 warnings；Web navigation 52 passed，Vitest 80 files / 411 tests passed；TypeScript、Web production build、Desktop main-process build 均通过。Vite 仍提示主 bundle 超 500 KB。只做了 Fake Provider/隔离数据库自动验证，未做浏览器人工验收或真实供应商/材料验证。A2 改动保持本地未提交、未推送。上述记录不改变本 ADR 的 Proposed 状态，也不表示 B/C/D 完成。

### B1（2026-11-01，本地未提交）

独立视觉配置使用 `NOTEBOOK_VISION_*`，设置面板允许对草稿值发送明确图像能力预检；预检采用随机红/绿/蓝/黄左右分区图，回答须匹配当次随机左侧颜色。结果按 base URL、模型和凭据指纹缓存，凭据指纹由数据目录内随机 HMAC 密钥生成，缓存和 Asset/ParseRun 快照不保存 API Key。旧环境中的 userinfo/query/fragment URL 会被视为无效，状态响应及处理快照不回显这些内容。`llm` 上传、图片上传和切换路线均在未通过当前配置预检时返回冲突；Worker 捕获一次有效视觉配置，同一份配置完成快照核对、能力检查和客户端构造，避免密钥轮换竞态。

协作者审查确认 URL 泄露、凭据轮换及检查/客户端凭据不一致等阻断问题已关闭。全量 `pwsh -NoProfile -File .\scripts\test.ps1` 退出码 0：Ruff 通过；后端 455 passed / 4 skipped / 2 warnings；Web navigation 52 passed、Vitest 80 files / 412 tests passed；Web TypeScript/生产构建和 Desktop main-process 构建通过。首次全量运行有一个 Notebook 草稿恢复 Vitest 用例时序失败，单文件复跑通过，之后完整复跑通过。Vite 主 bundle 仍有 >500 KB 警告。测试均为 Fake Provider/临时测试数据；未做真实供应商预检、真实材料或浏览器人工验收。

视觉 HMAC 密钥首次生成通过完整写入、fsync 后 hard-link 发布，避免并发读取半文件；未在不支持 hard-link 的数据目录上实测。并发预检可能丢失另一模型的缓存条目，但失败关闭并要求重新预检。

### B2（2026-11-01，本地未提交）

新增每个原始 Asset 的 CNY 整数分账本与供应商调用预留记录，迁移 `b6e1a9d420fc`。设置页维护文本/视觉价格、模型版本、公开来源、视觉图片 Token 上界、汇率日期/来源及安全缓冲；请求前基于 UTF-8 输入上界、最大输出与图片上界计算保守预留，usage 完整时结算，usage 缺失/超时/异常则保留额度并封锁该 Asset 后续付费。并发请求原子预留；共享调用按每个参与 Asset 重复计整笔费用。标准/全程 AI 解析、规划、正文生成、格式修复经过统一 guard；上传后自动关系收费任务已停用。新 API 提供每 Asset 账本，Notebook 资源行显示余额/状态。

Fake Provider/隔离 SQLite 验证覆盖预留结算、价格/汇率 fail closed、不确定费用、超额、共享 Asset、并发和超时后禁止重试。兼容修正后全量 `scripts/test.ps1` 已通过：后端 463 passed / 4 skipped / 2 warnings，Web navigation 52 passed，Vitest 80 files / 412 passed，Web/Desktop build 通过。未做真实供应商账单核对、真实文件/浏览器人工验收。此预算依赖维护者正确录入价目和图片最大计价上界，不能保证不遵守这些计价假设的供应商账单绝不超额。C1/C2 自动验证已完成；D 尚未完成，整体 ADR 继续保持 Proposed。

### C1/C2 与 D 第一阶段（2026-11-01，本地未提交）

两条 Notebook 历史路由现由同一 `NotebookPage` 实现承载，身份与 API 路由由 `useNotebookIdentity` 和 adapter 归一；课程专属资料管理按上下文显示，未分类 Notebook 不传伪造课程 ID。删除旧 `UnboundNotebookPage` 后更新历史对话测试。D 服务调整后完整 `scripts/test.ps1` 通过：后端 463 passed / 4 skipped，Web navigation 52 passed、Vitest 80 files / 412 passed，Web/Desktop build 通过。该测试未覆盖浏览器人工验收。

D 的第一步将生成任务创建逻辑下沉至 `app.services.generation_jobs`；Generation API 保持兼容端点，`notebook_generation_inputs` 不再反向导入 API Router。Ruff 通过，相关生成/预算/森林/DocumentIR 测试 43 passed / 1 warning；随后完整 `scripts/test.ps1` 也通过（后端 463 passed / 4 skipped，Vitest 412 passed，Web/Desktop build 通过）。`api/v1/notebook.py` 的生命周期、文档、历史、资源、建议和关系路由尚未拆分，因此 D 与整体 ADR 仍未完成，ADR 保持 Proposed。
