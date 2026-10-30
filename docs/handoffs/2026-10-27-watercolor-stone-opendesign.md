# 水彩环境与石头课程入口：已集成

后续用户要求自然石块与树根接地，当前实现以 [落地调整记录](2026-10-27-grounded-garden-refinement.md) 为准；下文保留为上一版记录。

用户本次明确要求不再使用 OpenDesign，改用设计技能直接执行。已使用 frontend-design、ui-ux-pro-max 和内置 imagegen 素材完成前端集成。继续在 feat/home-knowledge-forest 工作，未提交或推送。

## 设计与素材

按参考图使用暖白纸色 #faf8f0、石灰岩浅色、森林绿 #294636、苔藓绿、灰绿 #69715f。课程名用宋体类衬线字，工具栏沿用现有无衬线字。树保持主视觉，课程入口做成树下石牌。

内置 imagegen 生成的两项素材已复制到项目；保留原始 PNG 和透明通道。生成规格摘要：

- apps/web/public/assets/forest/watercolor-garden-background.png，1672×941：暖白水彩纸、柔和远山和校园、草地小花，主体留白，不画课程树、按钮或文字。
- apps/web/public/assets/forest/course-stone-plaque.png，2172×724 RGBA：浅色风化石灰岩、不规则边缘、苔藓与细草，中央留白、透明背景，不画课程名。

原始输出仍在 Codex generated_images 目录。上一轮两个未使用的简化 SVG 景物已移除。

## 实现边界

- botanical-surfaces.css 接入真实图片背景，统一森林绿侧栏、纸质搜索栏、主次按钮、圆形缩放控件和详情面板。
- 首页课程名使用原生 button，石牌仅为背景材质；完整课程名仍是 DOM 文本与标题，长名称换行。点击仍调用原有 onRoot(courseId)；移除重复的底部课程菜单按钮。
- 三棵树时按现有树位变量对齐各自石牌；树、叶、藤蔓和相机几何不变。
- 森林标题使用同一石牌材质，SVG 图片是装饰；原操作目标、缩放与回调保留。
- ForestPage 移除旧 ForestBackdrop 的叠加引用；组件文件保留。
- hover、active、focus-visible、reduced-motion 和窄屏布局均已处理。
- 本次未改后端、API、数据库；先前未提交工作保留。

## 验证

- 新增长名称石牌测试：课程名完整、原生按钮、单一入口、正确 courseId，先红后绿。
- 完整前端测试 310 项通过：38 个导航测试 + 272 个 Vitest 测试（53 文件）。日志 data/logs/watercolor-stone-tests.log。
- 森林材质接入后的相关回归 32 项通过，覆盖首页、森林页面/样式和生长绘制/场景。日志 data/logs/watercolor-stone-final-regressions.log。
- 最终 TypeScript 与 Vite 生产构建通过；仍有现有大 JS chunk 提示。日志 data/logs/watercolor-stone-build.log。
- 浏览器核实：石牌鼠标点击与 Enter、Esc 关闭和焦点返回、笔记本选择；三课程错落布局；390px 视口长课程名完整、无横向溢出；森林缩放、石牌菜单、窄屏适应全部课程。控制台无 error/warn。
- git diff --check 通过。

## 预览

本地 Vite 5173 服务。预览页渲染真实 App 和生产组件，仅在此页模拟 API，不读取或修改业务数据；右下角标有“外观预览 · 演示数据”。演示页与截图被 gitignore 排除，不进入生产包。

- 首页：http://127.0.0.1:5173/output/garden-polish-preview.html?view=home
- 森林：http://127.0.0.1:5173/output/garden-polish-preview.html?view=forest
- 可加 courses=1、courses=3、long=1 检查课程数量和长名称。
- 截图：output/playwright/watercolor-home-final.jpg、output/playwright/watercolor-forest-final.jpg。

上轮 OpenDesign 连接失败和简化 SVG 效果已由本轮直接技能实现替代，无需等待插件。
