# 自然手绘知识森林设计（2026-10-11）

用户确认：自然手绘；森林有完整培养方案的很多课程，正常桌面视口只显示 2–3 棵；按学期横向排列，基础/专业/综合应用形成错落层级，可手动调整；每门课一棵树，课程→讲次→笔记小节；叶子精确进入独立笔记；对应叶子之间用藤蔓表示跨学科关联。PDF/DOCX/粘贴文本培养方案先预览确认再创建/关联课程。未开始灰绿、在学自然绿、完成深绿，状态由用户确认，不自动完成，不把状态等同掌握。总览每课默认12片真实叶子，并补充当前已确认藤蔓的真实端点，聚焦展开讲次，空课不能造知识点。支持左右移动/拖动/触摸/缩放/搜索/小地图/键盘、返回恢复视口与展开，保护编辑草稿。

技术：现有 React19/TypeScript/Vite，SVG手绘模板与CSS；d3-zoom、d3-selection、d3-shape局部辅助；自定义确定性稳定位置布局，不用物理力模拟。React管理节点，D3管理相机。可见及邻近区域详细渲染，不加载全森林笔记正文。FastAPI/SQLAlchemy/SQLite/Alembic；现有独立workers.runner扩展森林任务，不使用请求内背景任务。跨课关系单独领域，不放宽旧KnowledgeEdge课程隔离。

AI：培养方案导入时自动提取课程/学期/层级/原文明确先修条件并保留来源；确认后落地。课件第一次及后续成功生成笔记时自动排队跨课候选；两端必须真实笔记与可核对依据，保留笔记版本；候选确认后才显示藤蔓，也能手动建立。模型未配置/失败明确显示，培养方案允许标明本地规则降级再手动修正。无真实笔记不生成知识藤蔓。保留原正文、旧ID、跨讲独立记录和user_locked。

## 前后端固定接口
Base /api/v1。数据字段 snake_case。API错误沿用项目detail。

ForestCourse = {course_id,name,semester:number|null,level:'foundation'|'professional'|'application'|'unspecified',learning_state:'planned'|'learning'|'completed',position:number,revision:number,note_count:number,material_count:number,prerequisites:string[]}。
GET /forest → {courses:ForestCourse[]}。PATCH /forest/courses/{course_id} → ForestCourse，输入expected_revision及可选semester/level/learning_state/position/prerequisites，独立乐观并发。旧有资料课程首次初始化learning，空课planned；后续上传不悄悄改状态。
详细树复用GET /courses/{id}/notebook的轻量outline（chapters.sections无正文），叶子复用notebookPath(courseId,{id,material_id})。来源复用笔记来源接口。
GET /forest/search?q= 返回最多40条 {course_id,course_name,note_id,title,material_id}，只搜索有效课程与笔记标题，不返回正文；用于跨视口定位，避免为搜索预加载全森林正文。

CrossCourseRelation = {id,source_course_id,target_course_id,source_note_id,target_note_id,source_title,target_title,source_course_name,target_course_name,relation_type:'related'|'prerequisite'|'application',reason,status:'pending'|'confirmed'|'rejected',origin:'manual'|'ai',source_revision,target_revision,stale:boolean,source_ref_ids:string[],target_ref_ids:string[]}。
GET /forest/relations?status=confirmed|pending|rejected|all → CrossCourseRelation[]。
POST /forest/relations，输入{source_note_id,target_note_id,relation_type,reason}，显式手动创建confirmed；POST /forest/relations/{id}/review，输入{decision:'confirm'|'reject'}，版本变化确认返回409；DELETE /forest/relations/{id} → {deleted:true}。已软删除课程/资料过滤，恢复后稳定ID仍有效；修订变化stale，不绘制未经复核的藤蔓。

CurriculumRow = {key,name,semester:number|null,level,prerequisites:string[],source_label,source_excerpt,existing_course_id:string|null}。
CurriculumImportRead = {id,status:'pending'|'processing'|'preview'|'confirmed'|'failed',filename:string|null,mode:string|null,warnings:string[],rows:CurriculumRow[],error_message:string|null,job_id:string|null}。
GET /forest/curriculum-imports → CurriculumImportRead[]（最近20条）；POST /forest/curriculum-imports multipart file(pdf/docx)或text，201返回CurriculumImportRead；GET /forest/curriculum-imports/{id} → CurriculumImportRead；POST /forest/curriculum-imports/{id}/retry → CurriculumImportRead；POST /forest/curriculum-imports/{id}/confirm，输入{rows:CurriculumRow[]} → {courses:ForestCourse[]}，preview才可确认，按key核对已解析来源，用户可修正name/semester/level/prerequisites/existing_course_id。不删已有课程/笔记；同名歧义人工确认。保留确认后的培养方案，首版一份有效方案，旧导入历史保留。
POST /forest/courses/{id}/suggest-relations → ForestJobRead；GET /forest/jobs/{id} → ForestJobRead；POST /forest/jobs/{id}/retry → ForestJobRead。
GET /forest/courses/{id}/latest-job → ForestJobRead|null，用于显示资料处理后的自动任务状态与失败重试。
ForestJobRead = {id,kind:'curriculum_import'|'cross_course_relations',status:'pending'|'processing'|'completed'|'failed',progress:number,error_message:string|null}。

## 后端共享模型约定（核心数据实现者创建）
在app/db/models.py新增：
ForestCourseProfile：course_id外键PK；semester nullable int；level string默认unspecified；learning_state string默认planned；position int；revision int默认0；prerequisites_json Text默认[]。
CurriculumImport：id UUID PK；filename nullable；stored_filename nullable（统一放data/originals）；input_text Text；status；mode nullable；warnings_json Text；rows_json Text；error_message nullable；created_at；confirmed_at nullable。
ForestJob：id UUID PK；kind；course_id nullable Course FK cascade；curriculum_import_id nullable CurriculumImport FK cascade；status；progress；error_message nullable；attempt_count；idempotency_key unique nullable；created_at/updated_at；started_at/finished_at/heartbeat_at nullable。
CrossCourseRelation：id UUID PK；source_course_id/target_course_id Course FK cascade；source_note_id/target_note_id Note FK cascade；source_revision/target_revision int；relation_type；reason Text；status；origin；source_ref_ids_json/target_ref_ids_json Text；created_at。无向related关系规范化两端ID防重复，其余有向同类型去重。单课程备份不得包含外课关系/全局培养方案/全局森林任务；全量包含培养方案原文件兼容旧v2。

## 验收
Ruff/pytest/npm test/npm build +真实浏览器。独立隔离数据库，迁移重复运行/旧库/并发修订/删除恢复/备份恢复；导入预览确认/错误重试/两阶段自动任务/版本与来源防伪；60规划课3门各200小节性能记录。真实培养方案、连续3讲、10编辑保护、30来源抽查、真实AI另列证据，未做不能宣称通过。

执行：在独立工作树开发，任务分支 feature/knowledge-forest，初始基线5693415，已按用户要求同步main3ab07b7。保留原目录全部未提交文件。用户授权推送任务分支并创建main目标PR；没有授权直接合并main。仓库公共协作规则见根目录 `agent.md`。不要输出或更改.env、密钥或真实课件内容。
