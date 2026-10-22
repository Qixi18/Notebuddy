# 首页文字区统一对齐与 AI 藤蔓落点

## 用户要求

- 所有课程的文字和操作入口统一放在树景下方，同排显示；各组文字的横向中心与对应树对齐。
- 树景继续保持三角错落。藤蔓关联依据项目内置 AI 对当前笔记的分析动态产生，前端只负责正确落点、数量上限与避让。

## 本轮修改

- `HomeCourseGarden.tsx` 用 `home-course-details` 包含课程名、状态、笔记本选择、继续阅读和添加入口。
- `home-courses.css` 只移动树 SVG，详情仅沿相同横向偏移；共享 subgrid 保持三组标题、目录和操作在相同横排。树行直接预留位移高度，移除整卡片平移。
- `vineGeometry.ts`：跨中间树的 clearance 路径由一条连续弧线经过预留点，消除之前两段转向造成的反向钩弯；没有 midpoint 的普通路径不变。
- `TreeVines.tsx`：由实时关联的知识点 ID 找出真实笔记本，再接到相应主枝。概览未展示该笔记本时接公共主干，不借用无关笔记本。结果更新会更新落点，空结果不绘制藤蔓。
- 每两门课最多四根显示藤蔓，多条具体 AI 关联由藤蔓叶子与列表承载，未删除业务记录。

## 内置 AI 链路核查

没有改写或替换模型生成链路，没有预设课程配对或伪造知识点关联：

1. `workers/material_worker.py` 上传解析完成，或 `notes/service.py` 保存笔记后，持久化 `enqueue_relations` 任务。
2. `forest/jobs.py` 将实际笔记原文、版本、来源证据交给项目配置的 `DeepSeekClient.complete_json`。
3. 校验模型返回的跨课笔记 ID、版本与双方 ref，写入 `origin=ai`、`activation_mode=automatic` 的关联。
4. 页面经 API 与 `useAutomaticVines` 发现任务、等任务完成刷新结果，并按实际课程、笔记本、知识点重算展示位置。

只读核查时本地共有 27 条 `ai / automatic / confirmed / stale=false` 关联。绘图几何属于视口与摆放规则，不充当知识关联推断。

## 验证

- 220 项前端检查通过（33 导航、187 界面）；生产构建通过。
- 后端 `test_automatic_vines.py` 与 `test_forest_material_worker.py` 共 14 项通过。
- 新回归先复现反向钩弯与错误笔记本落点，再验证修复；还覆盖运行时 AI 端点更换和空结果清除。
- 默认 1265×720 浏览器：三组详情 top 均为 567.26px、bottom 均为 713.66px；各详情横向中心与对应树 SVG 完全一致。
- 截图：当前聊天 visualizations 目录中的 `notebuddy-home-aligned-details.png`。
- 未修改课程数据、未提交或推送 GitHub。
