# 首页知识树与多笔记本设计

日期：2026-10-14。状态：用户已确认并授权实施。分支：feature/knowledge-tree-home。

## 已确认行为

首页以最近使用的2–3门课程树为主体，替换中央提问框、最近笔记和正在学习。知识森林包含全部课程，保持学期组织、培养方案和用户学习状态。一门课程一棵树，一本笔记本一根主枝，一个真实知识点Note ID一片知识叶子。

树根及根部铭牌打开“新建笔记本”“扩充现有笔记本”菜单；新建先命名，扩充先选择本课程已有笔记本，然后上传资料。生成真实笔记后增长枝叶。枝干及笔记本名称直接打开该本上次阅读位置；叶子直接打开所属章节并定位到知识点。原有用户正文、修订、来源、Note ID和课程隔离必须保持。

跨课程藤蔓由独立持久AI任务生成，通过当前版本、真实来源、课程归属和重复检查后直接显示，不再逐条确认。来源失效/笔记变化的旧藤蔓隐藏后重新分析；用户隐藏的关系不会被自动恢复。关联仍明确标注模型推断，不能当作教材事实。

右侧对话区域重新设计属于后续，本轮保留现有助手。笔记扩充沿用现有处理链，不增加自动拆书/合书、跨课程搬移或笔记本删除。

## 数据与兼容

新增Notebook(course_id,title,display_order,order_revision,is_default,tree_slot,created_at,updated_at)。Material与Note增加notebook_id；Note增加tree_slot（本内单调分配，不因目录重排/重解析改变）。知识概念保持课程级，正文与叶片以Note ID定位。章节排序与并发控制作用域改为笔记本。不同本同名知识点不合并正文。

有资料/笔记的旧课程迁入默认“课程名·课程笔记”；历史整理及已移除资料保持归属。空课程不创建假笔记本。迁移保全旧ID、正文、锁定、修订和来源，前置检查点、重复升级、旧库/旧包恢复和失败恢复均需验证。所有新增数据进入完整及课程范围备份；单课程备份不得泄露外课正文。

同本重复文件提示确认，异本同文件可独立导入。上传幂等键纳入本ID。读写同时校验课程与本归属。旧单数笔记本API指向默认本；旧Note/章节深链依据真实归属转新路由；旧上传未指定本ID时只有单本才兼容，多本必须明确报错。

NotebookReadingPosition按本存SQLite，字段chapter_id、note_id、mode(chapter/book)、section_offset（小节相对位置0..1）、revision、updated_at。叶子/搜索深链优先书签；枝干恢复书签；首次进入首个有效小节。正文稳定后只恢复一次；滚动节流保存，切换/离开补存；失败提示与待重试缓存。目标删除时进入原本目录提示，不串到别本。

Course.last_opened_at记录实际课程/笔记访问，森林展示、悬停、后台生成不更新。首页选择最新3门，无历史用创建时间兜底，不新增“最近使用”入口。≥1600px可用画布展示3树；普通桌面展示2树并可横移第三；窄屏1树。浏览器返回恢复既有集合/画布，主动首页访问重算。

## 接口契约

- GET/POST /courses/{course_id}/notebooks → NotebookSummary[]/NotebookSummary。
- GET/PATCH /courses/{course_id}/notebooks/{notebook_id} → NotebookRead（id,course_id,title,tree_slot,order_revision,chapters,historical_sections,removed_chapters）。PATCH修改title。
- GET .../chapters/{material_id}、PATCH .../order；沿用章节内容/顺序payload，校验本范围。
- GET/PUT .../reading-position → NotebookReadingPosition；PUT带expected_revision。无记录GET返回null。
- POST /courses/{course_id}/visit → {last_opened_at}，服务端记录时间；课程查询返回该字段。
- 上传表单增加notebook_id；MaterialRead、NoteRead、SectionRead、森林搜索结果包含notebook_id；SectionRead包含tree_slot。
- 新前端路由/courses/:courseId/notebooks/:notebookId?chapter=:materialId&section=:noteId；保留旧路由解析。
- 森林课程目录GET /forest/courses/{course_id}/tree返回本列表及轻量目录（不含正文），首页/森林使用同一契约。
- 跨课关系保留confirmed状态兼容，activation_mode=automatic/manual/null区分生效方式，界面显示自动关联/手动关联。拒绝记录保留。

## 视觉与场景

参考图保存在docs/design-references/knowledge-tree-target.png。只参考美术、构图，不套用图中右侧详情栏/主题主枝行为。

米白纸纹(#F7F5EA)、深绿(#284B39)、主叶绿(#6F8650)、浅叶绿(#B7BE77)、木色(#8B7657)、选中金(#D5BA63)。宋体风格标题、清晰无衬线操作文本，采用本地字体回退。苍劲弯曲、粗细渐变、树皮明暗、衔接的自然根系、非对称分枝；叶片有脉络/透色/角度变化，地面有少量草石，低对比远景。课程名根部铭牌文字独立渲染。

本地透明水彩素材+动态SVG，至少3种根干变化、6种叶片变化。树干/主枝由动态曲线及材质绘制，叶片独立image/文字/hit区域。禁止整张树图伪装动态；装饰植物不可交互且不冒充知识点。固定ID种子和持久槽位保证新增不洗牌，删除/恢复不挪旧入口。

总览最多6本主枝优先展开，每枝优先6真实知识叶标签，余量为明确非叶形聚合控件；放大、聚焦、搜索能到全部真实节点。搜索和选中藤蔓端点必须可见。空课程是幼树，无知识叶。新增实体局部生长400–800ms，尊重reduced-motion，不抢阅读焦点。

共享KnowledgeTreeScene，home/forest只改变课程集合和初始画布布局。独立返回状态，相机与实际视口保持。根/枝/叶事件不串；拖动超过6px禁止误触；可键盘操作、Esc关闭/恢复焦点，44px触控区域。标签避让，缩放隐藏次要标签。复用现有d3缩放，不引入3D引擎。

## 自动藤蔓

沿用ForestJob持久执行器，成功生成并提交后登记新增/修改Note ID集合，源每批<=30、外课证据候选<=18，保证31+新增点分批进入分析，不承诺全量语义召回。幂等键基于源集合/版本。提交前重读端点版本和实际引用；related对称去重、先修保留方向。合法结果直接生效，旧pending后台重新校验后生效，迁移不调用模型。stale隐藏并合并登记重新分析，rejected不复活；失败明确可重试，无模型不造线。

## 验收

后端Ruff/pytest，Web npm test/build，系统Edge真实操作；桌面1440x900、1366x768、1920x1080及390px窄屏；0/1/30/200知识点、1/3/10本、长中文/中英、空/失败/密集。

全链路树根→新建/扩充→资料上传→真实笔记→增长→叶子精确定位→返回→枝干续读。旧库重复迁移、同异本重复文件/幂等、正文保护、跨课隔离、备份恢复、30+关联分批、生成期间编辑/删除、隐藏不复活。

美术五维（木质根干、枝叶层次、构图、文字可读、交互反馈）各>=4/5，总>=22/25，以实际截图及缺陷说明佐证，仍由用户判断最终外观。粗线树干、重复叶形、漂浮/断枝、假知识叶、密集不可达必须返工。

60课、3本各200点隔离规模测试，记录硬件/浏览器；可见+邻近缓冲挂载，平移帧间隔p95目标<=33ms、点击本地反馈<=100ms，首屏美术资源<=3MB。代码、本地合成验证、真实材料/模型验收分开报告，未验证不写完成。
