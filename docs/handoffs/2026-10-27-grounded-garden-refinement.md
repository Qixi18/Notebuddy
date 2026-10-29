# 石块与树根落地调整

用户反馈上一版石牌死板、树和背景割裂，要求对照效果示意图调整，让树真实落在草地上。延续用户已指定的直接设计技能方式，不使用 OpenDesign。本次只改前端，未提交、推送或修改后端/API/业务数据。

## 设计与实现

- 取消重复的边框式石牌，改用两种不规则石灰岩：斜面、断角、苔藓、碎石与白色小花。按 courseId 的稳定 hash 选择形状，首页与森林一致；课程名仍为真实文字与原来的可操作入口。
- 收窄石块比例，使用楷体类深绿刻字；石块略遮挡根脚，形成树根在后、石块在前的关系。取消悬浮位移动效，hover 只轻微变色。长名称保留完整文本与无障碍名称。
- 将原先过低的背景草地改为连续平缓草地，校园与群山退到后景。首页调整背景地面高度并在底部做水彩淡出，避免图片硬边。
- 每棵树的 CourseCanopy 内加入透明草地根床，替代规则椭圆投影。它和树干处于相同坐标层、随缩放/拖动共同移动，不拦截点击、不参与生长蒙版。
- 森林改为较浅的前后错落，每块石头相对自己的树根定位，取消整组石牌统一水平线造成的悬空。世界 x 槽位和追加课程稳定性保留。首页三棵树同样收小深度差。
- forestTreeFrame 包含根床宽度；藤蔓避让区跟随新石块位置。布局版本改为 grove-v2-grounded，旧相机会自动重新取景一次。
- 窄屏三课程的阅读控件纵向排列，避免课程之间交叠；焦点、菜单、目录选择、叶片入口和 reduced-motion 继续沿用。

## 素材与提示词要点

素材均由内置 imagegen 按用户参考图生成/编辑，复制进项目；原始输出保留。所有文字和交互仍由前端渲染。

- apps/web/public/assets/forest/course-garden-stone-a.png：透明 PNG，2172×724。不规则矮梯形石灰岩，低左边、偏右高点，清晰天然前切面，少量苔藓、草与小白花，无字、无树、无装饰边框。
- apps/web/public/assets/forest/course-garden-stone-b.png：透明 PNG，2172×724。同材质伴生石块，左高右低斜边、右侧缺角，自然不同的植物分布，无字、无 UI。
- apps/web/public/assets/forest/sage-meadow-background.png：1672×941。沿用暖白纸纹与鼠尾草绿/橄榄绿，抬高连续平缓的前景草地，低对比远山与校园在后，上部保留文字与树冠留白，不画课程树和按钮。
- apps/web/public/assets/forest/tree-root-meadow.png：透明 PNG，2109×746。宽浅的草地根床、低矮苔藓、少量边缘碎石与野花，中心留给真实树根，四周水彩羽化，不画树干、大石牌或文字。

配色延续纸色 #faf8f0、深绿 #294636、刻字 #1f3d2b、灰绿和苔藓绿。旧素材保留以便对照，本版已不再引用。

## 验证

- 更新根部贴合与地面取景回归，旧布局先出现 3 个预期失败，新布局相关 12 项测试通过。日志 data/logs/grounded-grove-red.log、grounded-grove-green.log。
- 完整前端测试 310 项通过：38 个导航测试与 272 个 Vitest 测试（53 文件）。日志 data/logs/grounded-garden-tests.log。
- TypeScript 与 Vite 构建通过；现有大 chunk 提示仍在。日志 data/logs/grounded-garden-build.log。
- 浏览器核实两/三课程的根部贴合、390px 窄屏与长名称、石块 Enter 打开正确课程菜单、Esc 关闭、森林缩放。DOM 核实根床与树干共享同一课程的坐标祖先、石块相对根部 translate(0,40)。
- 预览继续使用隔离演示 API，不写业务数据：/output/garden-polish-preview.html?view=home；森林 view=forest；可加 courses=3 或 long=1。
- 新截图：output/playwright/grounded-garden-home.jpg、grounded-garden-forest.jpg。

此文档取代上一版素材说明中的当前效果描述。
