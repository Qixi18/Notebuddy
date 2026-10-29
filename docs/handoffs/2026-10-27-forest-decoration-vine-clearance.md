# 森林边角装饰与藤蔓避让

用户反馈纸纹底过素，并指出放大后藤蔓压在石牌和根部上。本轮只改前端显示与几何计算；已有课程、笔记、8 条 AI 关联及后端逻辑保持不变，未提交或推送。

## 背景

使用 frontend-design 和内置 imagegen，新增透明水彩叶片素材 `apps/web/public/assets/forest/forest-watercolor-corner.png`。以现有根部草地素材作为色彩/笔触参考，绘制鼠尾草绿、灰橄榄绿、少量赭黄色种子的边角枝叶，四周透明，无地平线、校园或固定地面。

森林保留暖纸色 #faf8f0 与纸纹，用低对比色晕、左下角叶片和右上角旋转叶片装饰；中心保持留白。伪元素位于画布背后、pointer-events:none，不参与树木世界坐标，不影响缩放、拖动或点击。首页插画背景未改。

完整生成提示词见 `../design-assets/forest-watercolor-corner-prompt.md`。

## 根因与修复

- 三树布局原先将跨越中间树的藤蔓中点放到 `between.y + 48`，与石牌的 `root.y + 40` 重叠。
- 既有 exclusion 只供关系叶片的 LOD 使用，没有约束藤茎、卷须及整条藤茎的点击路径。
- TreeVines 现在合并各树根床、现有石牌/课程控件区域作为保护区，并同时传给路径和叶片避让。
- buildVine 对原路线做碰撞检查。需要避让时保留两端真实笔记本嫁接点，将路线调整为平滑弧线，并根据保护区域的上边界求出中点高度，保留卷须及中段 44px 点击走廊所需空间。
- 输入关系 ID、分组上限、业务记录与点击回调不变。选中关系仍遵守保护区；原本已无冲突的路线保持原样。

## 验证

- 新增 4 个回归：旧实现 4 个均失败；修复后通过，覆盖完整藤茎、卷须、44px 点击范围，以及 0.35 / 0.8 / 1.6 缩放下的三树路线。
- 首页/森林藤蔓针对性回归 15 项通过。
- 完整前端测试 314 项通过：38 导航 + 276 Vitest（54 文件）。日志 `data/logs/forest-decoration-routing-tests.log`。
- TypeScript 与 Vite 构建通过，保留现有大 chunk 提示。日志 `data/logs/forest-decoration-routing-build.log`。
- 真实页面在 135% 缩放下对 3 条藤茎逐条采样，核对 12 个根部/石牌/按钮保护区，藤茎与卷须交叠均为 0。结果 `output/playwright/forest-vine-clearance-report.json`。
- 浏览器确认聚合藤蔓仍保留全部 8 个原始关系 ID，打开“离散数学与数学分析”的两条联系成功；首页也已回查。
- 正式页面 `/forest`，截图 `output/playwright/forest-decorated-clear-vines.jpg`。
