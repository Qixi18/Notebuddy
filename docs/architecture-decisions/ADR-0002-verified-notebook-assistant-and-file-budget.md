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

### S1–S7 整改批（2026-11-01 第二轮，本地未提交）

按 `2026-11-01-Notebuddy-最新源码复审-下一阶段开发路线图.md` 逐批实施，全部停在本地工作树：

**S1 P0-QA-01 输入物理隔离。** 新增 `app/ai/qa_evidence.py` 提供带类型的证据标识
（Notebook=`N*`、DocumentIR=`D*`、Web=`W*`）。`notebook_qa.py` 的 Stage-1 初稿请求
只序列化 Notebook 证据；DocumentIR 证据从 Stage-2 起才进入请求。`verification`
记录 `stage1_evidence_ids` / `stage2_evidence_ids` / `document_ir_evidence_count`
供事后审计。AnswerGate 只接受"格式合法 + 本轮输入内 + 被对应 review 批准"的证据编号，
因此 D 编号不能凭格式合法就冒充支撑。

**S2 P0-QA-02 统一核验后发布。** 新增 `app/ai/verified_answer.py`：课程/全局/历史
note 的回答一律先缓冲，再过证据门禁，才发 `status → delta → final`。SSE 不再外发
思维链原文（只留 `thinking_ms`/`thinking_chars`），也不落库 CoT；`GeneratorExit`
时只记录中断状态、不落未核验正文。JSON 入口同样经过该门禁。失败模式分明：
结构无效 → fail closed（不发布）；无证据 → `unverified_no_evidence`；
模型不可用 → `verification_unavailable`；部分主张缺证据 → `partially_verified`
并把口径写进 `verification.notice`（不污染正文）。

**S3 前端作用域与核验呈现。** 独立答疑页新增 Notebook 范围：`NotebookScopePanel`
用 `/notebooks/{id}/conversations` 建立真实 Notebook 会话，提问带
`notebook_context{notebook_id, revision}`，不复活旧 Note、不用伪 courseId；
`AssistantContextBar` 三档（全局/课程/Notebook）；`AssistantThread` 展示
已核实/部分未核实/未核验徽标。`AskScope` 收敛为 `global|course|notebook`；
`notebookApiAdapter` 用 `courseId: string|null` 表达未分类身份，`unbound` 只保留在
本地草稿键命名空间。

**S4 检索与来源可信度。** `retrieval/service.py` 拆出 `retrieve_notebook_body` /
`retrieve_document_ir` 两个受约束查询，DocumentIR 候选在 SQL 层用词面预筛并加
硬上界（`DOCUMENT_CHUNK_CANDIDATE_LIMIT`），不再无界取全量后 Python 排序。
`web_search/source_review.py` 增加来源类型/风险/发布年份与 `evidence_support`
词面评估；模型声称"某来源支持该主张"但词面完全不重合时降级为 `uncertain`。

**S5 预算验收。** 新增 Fake Provider 端到端与账单对账测试（见
`docs/acceptance-file-budget.md`）。口径仍为"配置假设下的拦截"，不做绝对保证。

**S6 Workspace 内部分层。** 抽出 `useNotebookDocument`（载入/草稿/revision/CAS/
冲突/生成后安全刷新）、`useNotebookResources`（课程资料、图片资产、恢复、预算展示）、
`useNotebookGeneration`（上传批次、轮询、重试、进度提示）。`NotebookPage.tsx` 由约
1209 行降到约 594 行，只做路由身份、深链、选区与页面组合；三条业务线互不直接引用，
生成完成后由结果对象驱动提示，不再互相调用。

**S7 Router 拆分。** `api/v1/notebook.py` 拆为 `notebook_routes/{common,lifecycle,
documents,revisions,resources,suggestions,relations,reading_position}.py`，原文件
降为薄聚合入口（重新导出 `router` 与路由函数名）。拆分前后 OpenAPI 完全一致
（144 条路径，方法/状态码逐项相同），并新增 `test_notebook_router_contract_snapshot.py`
与 `test_notebook_routes_module_boundaries.py` 防止契约漂移和重复注册。

**自动验证结果（本地，退出码 0）：** Ruff 通过；后端 502 passed / 4 skipped；
Web Vitest 81 files / 416 tests passed；TypeScript `tsc -b` 通过。
**未执行：** 真实模型/真实材料/真实账单/浏览器人工验收；ADR 仍为 Proposed，
需协作者审核实现与风险后才能改 Accepted。

### S8：运行时路由与业务边界复核（2026-11-03，Proposed）

当前代码复核发现，S7 完成的是 Notebook 路由文件按职责拆分、兼容聚合和 OpenAPI 契约冻结；
它没有完成 API 与业务服务/事务边界的分离。`notebook_routes/*` 多个 handler 仍直接依赖
SQLAlchemy Session、ORM 模型和提交事务；`common.py` 也包含资源归属校验与目录排序写入。
后续按垂直用例渐进下沉业务编排和事务，不以搬文件或一次性重写为验收标准，并继续守住
Notebook.document_json、revision/CAS 与 API 兼容契约。

复核时 Web 路由曾由 `App.tsx` 中的 `<Routes>` 声明，`main.tsx` 的 data router 只有通配路由；
本批已将路由改为 `appRoutes` 嵌套 route objects，由 `createBrowserRouter(appRoutes)` 直接挂载，
`AppRoot` 提供 Workspace 状态，`AppLayout` 提供共享 shell。课程/未分类 Notebook、森林、
回收站、助手及旧路径重定向保留；Data Router loader/action 与 route error boundary 尚未
接入。本轮新增路由匹配覆盖及实际 AppLayout→Outlet 侧栏跳转/dirty confirm 组件回归。

导航故障排查还观察到 Notebook 助手桥接注册值可能随渲染反复变化：
`useNotebookDocument` 曾将每次渲染新建的 `save` 对象作为 `useCallback` 依赖，
`useRegisterNotebookBridge` 又把该值写回布局 Context。先稳定暴露给桥接层的回调身份，
并将 Provider Context value 的身份稳定化，避免同一 bridge value 不变时消费者因父布局
重渲染而刷新。组件回归用例通过新建/加载 Notebook 桥接、父层无关重渲染、森林/回收站
切换和离开脏页面确认验证；仍需真实浏览器人工验收。

本次审查的实现范围按小批次进行：导航更新循环与离开拦截属于缺陷修复；后端 service
提取先选章节重排这一垂直用例：API handler 负责解析课程/Notebook 范围，
`app.services.notebook_order` 负责 expected revision、章节集合校验和原子提交；
新增接口回归用例覆盖成功、过期版本和重复章节 ID，保持两个旧路径与响应模型不变。
阅读位置 GET/PUT 的 scope、block/chapter 校验与 revision/CAS 持久化也移至
`app.services.notebook_reading_position`；原接口回归用例扩展到更新和过期 revision。
这两项 service 目前仍直接使用 SQLAlchemy/HTTPException，是渐进的 application-use-case
抽取，不宣称已建立独立 repository/domain 层。
新增跨域边界时同步更新 README、
`docs/architecture.md`、API/数据契约和对应测试。此提案仍需协作者审核；不得据此将本
ADR 标为 Accepted。真实浏览器人工验收应与自动构建/测试结果分开记录。

**S8 当前批验证（2026-11-03）：** Web `tsc -b && vite build` 通过；`npm run test -- --run
tests/app-navigation.test.tsx tests/notebook-document-bridge.test.tsx
tests/assistant-notebook-scope.test.tsx` 通过：Node navigation 52 项、Vitest 3 文件/7 项。
后端目标用例与 Notebook router contract/module-boundary 测试合计 8 passed / 2 warnings。
Ruff 与 Python `compileall` 通过。曾从仓库根目录直接运行 Vitest，因未加载 Web JSX 插件
出现 React 未定义；改为在 `apps/web` 工作目录运行后通过。生产构建仍提示主 chunk >500 KB。
尚未做真实浏览器人工验收或全套后端回归；不能把该批结果外推为整体接受或完成。

**S8 后续边界实现（2026-11-03）：** 新增 `app/services/notebook_document.py`，统一正文保存、
历史恢复、图片附件/Asset 所有权校验及事务提交/回滚。`documents.py` 和 `revisions.py` 的
API handler 保留 Notebook 路由身份解析及响应组装；普通编辑和历史恢复都继续通过
`notes/store.py::write_document` 写入，保留唯一的 revision/CAS、历史快照和派生索引路径。
建议审核及批量应用同样调用服务中的图片归属校验，移除 `notebook_routes/common.py` 中的
资源业务规则。该服务仍依赖 SQLAlchemy 与 FastAPI HTTPException，是 use-case 边界收敛，
不是独立 domain/repository 架构。按用户本轮要求，本批未运行测试或启动服务；实现尚未
经过本轮验证，ADR 仍为 Proposed。

**S8 本轮代码修改（2026-11-03）：** 将处理路线及 Provider 配置实现迁至
`document_processing/config.py`，`service.py` 改为依赖配置模块，旧 `routes.py` 保留兼容重导出。
Notebook 建议单条/批量审核编排迁至 `app/services/notebook_suggestions.py`，继续经
`notes/store.py::write_document` 执行唯一正文 CAS 写入。Notebook 生命周期服务统一检查普通资料、
图片处理和生成任务，供批量、课程内和未分类删除共用。图片 Worker 仅在终态写入
`finished_at`，任务重新认领或回到 pending 时清空该值。以上修改保持既有 API 路径、响应契约和
正文存储机制；针对性测试与静态检查待执行，ADR 状态仍为 Proposed。

随后继续完成：所有应用内调用端迁至 `document_processing.config`；章节重排 Service 只返回业务结果，
由 Route 组装 Notebook API 响应；Notebook 生命周期的批量管理、创建、重命名、绑定、解绑、移动、
恢复与删除事务下沉至生命周期 Service，Notebook 附件/封面变更下沉至资源 Service；路由边界测试增加
Service/Document Processing 不反向依赖 API、正文写入调用入口约束。Web 移除 Workspace 中未使用的
旧 Note 正文编辑状态，修复课程旧 Notebook URL 到具体 Notebook 的解析并保留查询参数；全局与关键
Notebook/森林/答疑路由加错误页，侧栏、脏正文导航保护和助手坞控制分别抽离，Notebook/答疑/森林及
助手坞改为按需加载。PPTX/DOCX 明确为受限兼容格式，避免接口接收被误解为解析质量保证。整体状态待
用户评估；本轮仅做必要的轻量检查，ADR 仍为 Proposed。

**S8 分层续改（2026-11-03，Proposed，未提交）：** 关系 Service 统一 Notebook 普通关系、Forest 锚点关系、删除 suppression 与锚点刷新；Notebook 生命周期变更时，在事务内为受影响课程登记关系重算。关系展示仍要求两个端点属于不同有效课程，锚点指纹只依赖正文；解绑/同课程移动会隐藏记录，恢复跨课程归属后可再次展示。Generation 重试和取消由 `generation_jobs.py` 承担，输入登记改为传递普通 asset ID 列表。生命周期、资源、建议、关系和 Generation 用例使用框架无关异常，新建议审核 Service 不依赖 FastAPI Schema。前端 RouteErrorPage 隐藏原始异常；旧 Notebook Redirect 独立组件按课程归属检查目标并优先选择默认 Notebook。新增关系迁移和架构边界测试。针对性测试已运行；Materials/Agent 分层、完整回归及人工验收尚未完成。此续改不得视为 ADR 已 Accepted。

Materials 路由已按 assets、documents、materials、processing、uploads 拆分到 `app/api/v1/material_routes/`；聚合入口和 API URL 保持不变。上传 Service `app/services/asset_uploads.py` 组合既有文件接入流程、Upload Batch 与 Generation Input 登记，并复用 staged Asset 的恢复机制。解析重试、重新解析、OCR、图片重试、处理路线切换和取消由 `app/services/asset_processing.py` 负责。Agent 会话校验、执行、验证、消息持久化以及失败/中断处理迁入 `app/services/agent_execution.py`；`agent.py` 仅保留请求命令映射、HTTP 错误映射和 SSE 编码。已执行 Agent 相关定向回归；Materials 相关回归及完整验收仍未完成。

