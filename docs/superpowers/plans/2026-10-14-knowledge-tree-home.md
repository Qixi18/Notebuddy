# 首页知识树与多笔记本 Implementation Plan

> 执行：逐项实施，完成后独立检查规格与代码质量，再执行下一项。使用 subagent-driven-development；本项目原目录任务分支开发，全部产物回到原目录。

**Goal:** 首页最近课程树、森林全课程、多本主枝、精确知识叶、续读、自动藤蔓及自然水彩美术。
**Architecture:** FastAPI/SQLite存业务与书签，Notebook独立实体。React共用SVG树场景，d3视口，本地水彩素材，稳定槽位布局。沿用解析/来源/修订/持久执行器。
**Tech Stack:** 现有Python/FastAPI/SQLAlchemy/Alembic、React/TypeScript/Vite、d3。
**Spec:** ../specs/2026-10-14-knowledge-tree-home-design.md

## Global Constraints

- 一课一树、一本一主枝、一真实Note ID一知识叶。根菜单新建/扩充后上传；枝续读；叶进章节精确知识点。
- 自动藤蔓经过真实引用/版本检查后显示，用户拒绝不复活；保留课程隔离、用户正文、来源、旧ID和旧入口。
- 原目录feature/knowledge-tree-home；只提交本任务文件，作者mawenzhe33；不输出配置或密钥，不写合成数据进用户库。
- 森林和首页共用树；采用参考图自然水彩质感，独立标签/hit区域，不用整张树图片伪装动态。
- 真实模型/资料与合成验证区分；没有证据不能写完成。

## Review Focus

1. 旧Note/历史无material笔记在迁移后仍有正确本归属及来源。
2. 在B本上重复用A本上传幂等键不返回A本任务。
3. 叶子明确定位不被续读或加载刷新覆盖。
4. 关联生成过程中编辑/删除不可写入有效旧版本关系；拒绝不复活。
5. 大量枝叶不丢入口、不洗牌、没有不可点击遮挡。

## Task 1: 后端多笔记本、阅读位置与兼容

Files: 后端db/models、新增Alembic、notes/notebook、schemas、api/v1/notebook/materials/courses/forest、services/uploads/backup/restore、必要生成归属与测试。
Interfaces: 严格实现Spec接口契约，新增Notebook和ReadingPosition；Material/Note/SectionRead带notebook_id，SectionRead带tree_slot。GET /forest/courses/{id}/tree输出{course_id,notebooks:NotebookRead[]}。
- [ ] 先写有行为意义的失败回归：三本隔离/同名独立、旧迁移ID正文修订、书签归属/409、重复文件/幂等与旧API。
- [ ] 验证RED后实现最小模型迁移/API/上传/生成归属/本范围排序/书签/访问时间。
- [ ] 完整与课程备份、旧恢复、重复启动、删除资料/恢复保持归属和槽位。
- [ ] Ruff和完整pytest，报告RED/GREEN及真实退出结果；本任务不改Web和跨课AI逻辑。
- [ ] 身份核对后只提交本任务后端文件；写任务报告。

## Task 2: 水彩树形与共享场景

Files: Web features/forest新增树场景/槽位布局/渲染/样式及单测；复用ForestTree、useForestCamera；类型/api由此任务按后端实际契约接入；本地素材由主代理提供。
Interfaces: KnowledgeTreeScene接收course集合与CourseTree{course_id,notebooks}；onRoot(courseId),onNotebook(courseId,notebookId),onNote(courseId,notebookId,section),onRelation(relation)。单树home/forest几何一致。现有森林页集成在Task3。
- [ ] 先写失败行为回归：稳定book/Note槽位新增/恢复、聚合全部可达、根/枝/叶不串、拖动阈值/键盘。
- [ ] 实现动态木质SVG、透明素材叶/根、独立标签hit、主枝归属、可视裁剪、密集聚合、搜索/端点显露、局部增长。
- [ ] 空课程无知识叶、3根干/6叶变化、颜色字体按Spec；不将完整树图片作为业务结构。
- [ ] 相关测试、npm test、npm run build；真实截图美术证据在Task5。
- [ ] 提交任务Web文件并报告，不改上传/NotebookPage/首页/森林主页面（Task3所有）。

## Task 3: 首页/森林、树根上传与阅读定位

Files: Web HomePage/ForestPage/NotebookPage/NotesLibraryPage/App/AppLayout/workspace/api/types/navigation、上传现有UI及必要新对话框、行为测试。
Interfaces: 使用Task1真实API、Task2共享场景。新plural路由，旧Note/章节路由归属解析；reading-position深链优先；Course.visit持久最近访问。
- [ ] 先写失败流程回归：根菜单目标本上传、枝续读/首次本、叶精确知识点、返回相机、未保存保护、首页访问时间规则。
- [ ] 接通根部新建/扩充流程，失败任务保持本与旧内容，新叶由成功目录刷新触发。
- [ ] 保存本内书签/相对滚动，节流与离开补存，409不静默覆盖，正文稳定恢复一次；损坏/删除书签回原本目录提示。
- [ ] 首页选3课程、常规2树横移第3/宽屏3/窄屏1，去旧中央区域，助手保留；森林所有课程/学期/培养方案/学习状态保留。
- [ ] 书架多本、统一所有跳转与归属，课程与书签不串；返程保持集合/画布。
- [ ] npm test/build通过后提交并报告。

## Task 4: 自动藤蔓与任务可靠性

Files: 后端forest/jobs/service/api/schema/db迁移、material_worker/notes保存成功钩子与测试；Web关系面板、轻量刷新与任务提示。
Interfaces: activation_mode字段；状态confirmed兼容但UI称生效，源NoteID版本全集分<=30批、每批候选<=18，保留持久ForestJob/idempotency。
- [ ] 先写失败回归：无confirm显示、新增31+点全分批、旧pending重新校验、拒绝不复活、版本变化/来源无效/删除、幂等重试。
- [ ] 生成成功hook与用户修改hook合并登记，提交前条件验证，合法直接生效；stale旧线隐藏、自动重算；模型未配/失败明确。
- [ ] 前端显示自动/手动关联、可查看来源理由、隐藏/主动恢复；首页/森林及时刷新，密集端点不把画布撑坏。
- [ ] 后端完整pytest/Ruff、Web test/build通过后提交报告。

## Task 5: 综合验证、质量审查与交接

Files: 隔离QA样例脚本、相关文档/验收/交接，仅修复上述任务已确认的问题。
- [ ] 生成独立合成资料，三本同名点、跨课证据、0/1/30/200叶和1/3/10本、60课规模。不能种入用户数据。
- [ ] 系统Edge完成树根→上传→生成→叶→返回→枝续读→自动藤蔓；四种视口、长中文/中英、密集和键盘。
- [ ] 保存真实截图并对照参考，五维各>=4总>=22；未达标针对性修正。
- [ ] 记录首屏资产、平移p95/点击反馈环境和实测；模型配置通过状态接口检查，不输出密钥。
- [ ] 全量Ruff/pytest/Web test/build、git diff --check、迁移/恢复回归；运行结果区别合成/真实AI验收。
- [ ] 整分支独立审查、修复、限定复审；更新API/架构/验收/AGENTS和交接；原目录启动交付。
- [ ] 提交任务文件，按授权准备任务分支PR，未获合并授权不合并main。
