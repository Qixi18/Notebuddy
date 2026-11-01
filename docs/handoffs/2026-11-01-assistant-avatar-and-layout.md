# 答疑桌宠头像与布局修复

分支：`feat/overall-inspection`。基线：`822270ea7ad98e8ab08de0a25599f930b33c1378`。开始前检查工作区并 Fetch origin，与本功能分支的 main 基线比较为 0 / 0，保留之前全部未提交修改。未提交或推送。

## 发现与修改文件

- `apps/web/src/styles.css`：右侧 48px 圆形头像中的图片已经加载，但旧 compact 样式将舞台撑高到实测 91px，人物被容器裁掉。改为定尺寸舞台、绝对定位图片和面部裁切，并清除窄屏旧立绘样式带来的负边距。此修复复用于全部 compact 头像。
- `apps/web/src/course-assistant.css`：34px 浮出锚点和 38px 窄屏头像原来只指定宽度、仍保留 48px 高度；现统一填满父容器。顶部操作按钮保持横排文字，窄屏标题和操作区分行，状态文案保持完整一行。右侧栏高度改用动态视口，中间内容可滚动，避免矮窗口裁掉发送区。
- `apps/web/src/assistant-workspace.css`：标题分配剩余宽度，避免长课程名挤压按钮。
- `apps/web/src/features/assistant/AssistantDock.tsx`：为上下文、消息及建议区域增加滚动容器，头像标题和输入表单保留在外侧。
- `apps/web/src/features/pet/usePetViewport.ts`：提取共用的 900px 宽屏判断。
- `apps/web/src/features/pet/PetAvatar.tsx`、`apps/web/src/pages/AssistantPage.tsx`：桌宠及身份栏使用一致的实际展示模式；保留浮出偏好时，缩到窄屏仍展示栏内身份，恢复宽屏后回到浮层，不覆盖原有位置或大小记忆。
- `apps/web/tests/assistant-layout.test.tsx`：新增浮出 → 窄屏 → 宽屏的真实页面回归，验证身份可见与偏好保留；先观察旧实现失败，再实现通过。

## 验证

- 相关四个测试文件 54 项通过。
- 最终完整前端：`npm test -- --maxWorkers=2` 退出码 0，52 项 Node + 404 项 Vitest，共 456 项通过，无失败或跳过。
- `npm run build` 退出码 0，保留现有的大 bundle 警告。`git diff --check` 通过。
- 日志：`.runtime/logs/assistant-avatar-all-tests.log`、`.runtime/logs/assistant-avatar-build.log`；预期失败证据 `.runtime/logs/pet-visibility-red.log`。
- 浏览器检查实际组件与正式 CSS，使用合成课程、空会话和无模型请求的检查页；覆盖右栏展开/收起、键盘调宽与双击复位、完整答疑页、浮出/召回、窄屏模式切换。48px 头像内部舞台实测 46.67px（扣除边框），34px 和 38px 头像内部舞台均与父容器相同，图片正常加载。
- 1000×500 下发送按钮底部从修复前 516.9px 降到 456.9px；390×480 下底部为 436.9px，输入区与收起按钮可见，中间区域可滚动。390×844 下身份栏可见、浮层隐藏、无水平溢出，顶部按钮未挤成竖排。
- 编辑过程中旧检查页曾受热更新的上下文版本影响，刷新后恢复；最终重新打开检查页及完整答疑页均正常加载。
- 截图：`apps/web/output/tree-inspection/assistant-avatar-fixed.jpg`、`pet-mobile-fixed.jpg`；检查页及图片均被现有输出目录规则忽略。

本次未运行后端、真实课件、OCR 或外部模型验收，未读取真实会话内容，未写入真实数据库或服务端配置。检查页使用 `localhost`，用户正式页面使用 `127.0.0.1`；用户页面未被强制刷新。最终浏览器视口已恢复，临时检查标签页已关闭。
