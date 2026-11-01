# 树干分生与课程石头底座

分支：`feat/overall-inspection`，基线：`822270e`。改动未提交、未推送。

## 结果

- 树干与主枝共同生成：一本笔记本延续单一主干，两本形成不对称 Y 形，三本保留中央主干及错位侧枝。
- 三种树根素材各自对应树干走向。主枝从真实父树干曲线取连接点与方向，粗细不超过父干；森林纵向展开时补偿连接方向与横截面。
- 首页和森林共用同一套几何与材质；保留空课程的原始裸枝材质。笔记本和知识点 ID、归属、点击以及叶柄坐标计算沿用现有契约。
- 石头由独立装饰图片承载，按钮高度有界；长名称最多显示三行，完整名称保留在 accessible name 和原生悬停提示中。

## 文件

- `apps/web/src/features/tree/naturalBranchGeometry.ts`：共享树干与分生、纵向展开补偿、父子连接审计。
- `apps/web/src/features/tree/courseCanopyGeometry.ts`：将展开比例传入几何生成。
- `apps/web/src/features/tree/CourseCanopy.tsx`：绘制一次共享树干、统一树皮并羽化根部。
- `apps/web/src/features/tree/NaturalBranchWood.tsx`：取消主枝接头描边造成的轮廓缝。
- `apps/web/src/features/tree/TreeSprites.tsx`：同步素材用途注释。
- `apps/web/src/features/home/HomeCourseGarden.tsx`：独立石头图片。
- `apps/web/src/features/forest/botanical-surfaces.css`：固定底座层、响应式内边距和长名称限行。
- `apps/web/tests/trunk-silhouette.test.tsx`：新增树干、九种组合及展开连接回归。
- `apps/web/tests/natural-branches.test.tsx`：更新旧的“所有分枝同点出发”断言，检查错位父子连接。
- `apps/web/tests/tree-directory-growth.test.tsx`：等待动画 effect 的回归断言，避免目录先渲染导致竞态。
- `.gitignore`：忽略本次纯合成浏览器检查页和截图。
- `docs/superpowers/plans/2026-10-31-tree-trunk-and-stone.md`：实现及验证计划。

## 验证

- 先观察新增的连接测试失败，再实现并通过。相关六个文件共 41 项测试通过。
- 完整前端普通运行曾通过：49 项 Node 测试、392 项 Vitest 测试。另一轮与构建同时执行时，`forest-page.test.tsx` 的 `two returns preserve camera and directory at 900px` 达到原有 5 秒超时；最终降低 worker 数复核，结果见下方记录。
- `npm run build` 退出码 0；保留已有的大 bundle 警告。
- `git diff --check` 通过。
- 独立代码审查未发现 Critical / Important 问题。
- 浏览器检查三种根部 × 一、二、三主枝；另外挂载正式 `AppLayout`、`HomePage` 与 `ForestPage`，使用合成 API 响应及正式 CSS 检查生产排版。
- 390px 的正式首页检查：三块石头图片均加载，长名称底座高度为 92px，各自未遮挡下方笔记本入口；页面无水平溢出。手机检查以 DOM 尺寸为证据，桌面效果另有截图。
- `apps/web/output/tree-inspection/` 为忽略的临时合成页面；`home.html` 展示正式页面组件，`index.html` 是九种树形的独立对照页。桌面截图为 `home-desktop.jpg`、`forest-desktop.jpg` 和 `desktop.jpg`。

未执行后端、真实课件、OCR 或外部模型验收；未读取、迁移或修改原有数据库。

## 最终复核

`npm test -- --maxWorkers=2` 退出码 0：49 项 Node 测试与 77 个文件中的 392 项 Vitest 测试全部通过，无跳过。最终构建退出码 0。日志：`.runtime/logs/tree-inspection-web-tests.log`。

## 后续调整：首页动效与设置排版

- 首页生长时长增加 40%。`growth/timing.ts` 集中定义基础生命周期和首页倍率；`paint.ts` 同比缩放阶段时长、间隔及兜底清理；`useGrowthPlayback.ts` 同步延后回执清理。`HomeCourseGarden.tsx` 与 `HomeCourseTree.tsx` 使用同一倍率，首页关闭叠加的快速 CSS 生长动画。森林与藤蔓沿用默认倍率。
- `SettingsPanel.tsx` 的“默认文档处理路线”沿用 `.field` 的上下排版；`styles.css` 将选择框设为整行 44px 高，不改设置值或保存行为。
- `tree-growth-paint.test.tsx` 与 `tree-growth-playback-current.test.tsx` 新增回归，先观察到旧时长和过早清理的失败，再验证放慢、清理及原有默认速度。
- 最终完整前端验证：49 项 Node + 395 项 Vitest 共 444 项全部通过；构建退出码 0，仍有已有的大 bundle 警告；`git diff --check` 通过。日志：`.runtime/logs/home-animation-settings-tests.log`。
- 浏览器使用合成配置检查正式设置组件：390px 下标签与选择框间隔 6px，选择框高 44px，无重叠或水平溢出。截图：`apps/web/output/tree-inspection/settings-fixed.jpg`。合成首页动效页验证原生遮罩播放且叠加 CSS 动画为 `none`；未改真实数据或配置。
- 本次未运行后端、OCR 或外部模型验收。

## 后续调整：先修公式，再修石头字号

按用户要求分两阶段执行，先完成公式的相关回归、构建和浏览器检查，再实现字号计算。

### 叶片公式预览

- `apps/web/src/features/home/HomeNotePreview.tsx`：摘要及标题使用现有 ReactMarkdown / remark-math / rehype-katex 管线，禁用信任扩展、原始 HTML、图片与链接。取消前端 145 字符的二次截断，保留 API 原有摘要边界；不修改 Notebook 正文或 API 数据契约。
- `apps/web/src/features/home/note-preview.css`：限制摘要的可视高度，长公式可滚动，沿用紧凑预览样式。
- `apps/web/tests/home-note-preview-math.test.tsx`：覆盖集合符号、黑板体字母、跨旧截断边界的完整公式、标题公式和只读内容。
- 公式阶段相关 21 项测试及构建通过。合成浏览器预览中 4 个公式渲染成功、无 KaTeX 错误，黑板体字体为 KaTeX_AMS；截图 `apps/web/output/tree-inspection/math-fixed.jpg`。

### 首页石头字号

- 新增 `apps/web/src/features/home/stoneTitleFit.ts` 与 `StoneCourseTitle.tsx`：按中英文字数估算字号，随后用真实字体、换行及石面可用尺寸测量，在 10–27px 内选取合适字号，最多三行；过长或在最小字号仍放不下的名称缩为带省略号的前缀。按 Unicode 码点截取，保留完整 accessible name 与悬停提示。
- `HomeCourseGarden.tsx` 接入测量组件；`botanical-surfaces.css` 缩小文字可用区域到石面的中央留白，移除旧的三行静默裁切和文字偏转。
- `apps/web/tests/stone-title-fit.test.ts`：覆盖普通长名称缩字号、超长名称省略、无空格英文和 Unicode 字符。
- 390px 浏览器检查 9 个合成样例，文字均位于石面内边距区域且未被裁切；最低测得字号 10.4px。桌面常见长中文名完整显示，超长中英文名带省略号。截图 `apps/web/output/tree-inspection/stone-title-fixed.jpg`。

最终验证：52 项 Node 测试 + 78 个文件中的 399 项 Vitest 测试，共 451 项通过；构建退出码 0，仍有已有的大 bundle 警告；`git diff --check` 通过。日志 `.runtime/logs/leaf-math-stone-title-tests.log`。本次未运行后端或外部模型验收，未操作原有数据库和配置。

## 2026-11-01：侧边栏寄语可编辑

- `apps/web/src/components/SettingsPanel.tsx`：设置顶部新增“个性化 / 侧边栏寄语”，使用多行输入框，最多 80 个字符，说明留空保存恢复默认。沿用底部“保存配置”和“取消”。
- `apps/web/src/components/useSettingsDraft.ts`：将寄语计入待保存项；仅修改寄语时不调用服务端配置写入。与模型配置一起保存时，先确认服务端保存成功，再保存寄语；服务端读取失败时仍可单独编辑寄语。
- `apps/web/src/features/navigation/sidebarQuote.ts`：默认文案及当前浏览器 localStorage 持久化；保存后核对写入结果，浏览器禁止存储时显示错误。
- `apps/web/src/components/AppLayout.tsx`：从保存值显示寄语，监听设置保存和跨标签页存储变化。
- `apps/web/src/garden-theme.css`、`apps/web/src/styles.css`：寄语保留换行并允许长词折行；补充设置输入框样式。
- `apps/web/tests/sidebar-quote-settings.test.tsx`：真实侧栏和设置组件联测，覆盖保存后立即更新、重新挂载保留、取消、空白恢复默认、后端不可用时保存、组合保存失败后的重试。先观察 4 项测试因缺少编辑入口失败，再实现并通过。

验证：相关 15 项测试通过；完整前端 `npm test -- --maxWorkers=2` 退出码 0，52 项 Node + 403 项 Vitest 共 455 项通过，无失败或跳过。`npm run build` 退出码 0，仍有已有的大 bundle 警告；`git diff --check` 通过。日志 `.runtime/logs/sidebar-quote-all-tests.log`、`.runtime/logs/sidebar-quote-build.log`。

浏览器使用合成课程及配置验证多行保存和刷新保留；390px 下输入框及保存按钮可见，页面无水平滚动。验证后通过正式设置界面恢复默认寄语，保留正式网页的设置面板供用户编辑。截图 `apps/web/output/tree-inspection/quote-settings-fixed.jpg` 只包含寄语区域。本次只写浏览器寄语偏好；未修改 `.env` 或数据库，未运行后端、OCR 或模型验收。未提交或推送。

## 2026-11-01：移除首页提示，森林保留自然叶色

- `apps/web/src/pages/HomePage.tsx`：删除“随窗口自适应 · 点击枝叶继续阅读”。
- `apps/web/src/features/home/home.css`、`home-courses.css`、`apps/web/src/features/forest/botanical-surfaces.css`：清除该提示的无用样式，知识关联按钮继续右对齐。
- `apps/web/src/features/tree/knowledge-tree.css`：移除按课程状态施加给叶片的透明度、低饱和度和亮度处理，包含空树的树苗冠部。状态标识和首页课程选择行为保留。

浏览器先复现未开始课程的叶片 `saturate(0.42)`、透明度 `0.65`，修改后实际森林组件中三种状态共 108 张叶片图片的 filter 均为 `none`，透明度均为 `1`。首页提示节点不存在，搜索仍可见，无水平溢出。使用合成课程验证，未改变真实课程状态；效果图 `apps/web/output/tree-inspection/forest-natural-leaves.jpg`。

完整前端测试退出码 0：52 项 Node + 403 项 Vitest 共 455 项通过，无失败或跳过。构建退出码 0，保留已有的大 bundle 警告；`git diff --check` 通过。日志 `.runtime/logs/forest-natural-leaves-tests.log`、`.runtime/logs/forest-natural-leaves-build.log`。本次未运行后端或外部模型验收，未写真实数据库或配置，未提交或推送。
