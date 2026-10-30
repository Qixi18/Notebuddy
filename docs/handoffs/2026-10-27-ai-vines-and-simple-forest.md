# 首页标题栏删除、简洁森林与真实 AI 藤蔓

用户要求移除首页“正在学的课程 / 3 门课程”横栏，尝试内置 AI 生成藤蔓，并将可缩放森林改成简单背景。本轮未修改后端逻辑、密钥或模型配置。

## 前端

- HomeCourseGarden 移除整个 section-head DOM。首页背景地面相应上移 36px，保留树根与草地的落地关系。
- 森林移除固定校园/草地远景，使用浅色纸纹。每棵树的局部根部草地保留在树坐标系内，随缩放和拖动共同移动。
- 首页保留插画背景；笔记本、叶片、石块和藤蔓的原有交互保留。

## AI 实测

此前手工测试笔记没有课件引用，正常跨课生成会在来源校验阶段被挡住。本轮准备了 4 份明确标注“本地人工合成测试资料；非教材原文”的 DOCX，通过实际解析器产生原文块，将其中 10 个知识点关联到真实可核对的引用。没有伪造解析结果或教材来源。

- 保留三门课程、3/3/2 本笔记本与 18/18/12 个知识点及稳定 Note ID；未覆盖手工笔记正文。
- 已创建调整前检查点，位置保存在本地 setup 清单。
- 项目内置 DeepSeek 客户端实际 JSON 生成成功，随后通过既有 suggest-relations 接口与任务处理器执行一次离散数学跨课任务。
- 任务 completed，产生 8 条 origin=ai、activation_mode=automatic 的有效关联，连接离散数学与数字逻辑、数学分析。8 条均 confirmed、stale=false，两端引用均非空。
- 首页显示聚合藤茎；浏览器打开“离散数学与数学分析”的藤蔓详情，看到两条真实模型推断与依据。
- 仅执行本次指定任务，未启动长期全局 worker，不会顺带处理其他用户任务。

准备/执行脚本及结果在本地忽略目录：data/manual-test-setup/vine_ai_test_20261027.py 和同名 .json。原 DOCX 保存在正常 originals 目录。不要把测试生成的 AI 关系当成人工连接，也不要把合成资料称作教材原文。

## 验证与展示

- 完整前端测试 310 项通过（38 导航 + 272 Vitest，53 文件）。日志 data/logs/home-strip-simple-forest-tests.log。
- TypeScript 与 Vite 构建通过，保留现有大 chunk 提示。日志 data/logs/home-strip-simple-forest-build.log。
- 浏览器确认：首页无横栏、真实藤蔓存在且可打开依据；森林纸纹底下放大到 53% 正常，恢复适应全部课程后展示。
- 正式本地页面，不是模拟 API 的外观预览页。
- 截图：output/playwright/home-ai-vines.jpg、simple-forest-ai-vines.jpg。
