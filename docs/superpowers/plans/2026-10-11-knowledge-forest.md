# 自然手绘知识森林 Implementation Plan

> 执行采用按边界并行实现、统一集成与独立审查。所有代码改动先做能证明用户可观察行为的失败测试。

Goal：交付手绘森林、稳定叶子跳转、培养方案预览确认和经审核的跨课藤蔓，并推送GitHub PR。
Architecture：SVG场景与业务数据分离，现有笔记小节ID作为叶子身份；新增森林领域和数据库持久任务。
Tech Stack：React/TypeScript/SVG/CSS/D3，FastAPI/SQLAlchemy/SQLite/Alembic，现有解析器与AI接口。
Spec：docs/superpowers/specs/2026-10-11-knowledge-forest-design.md。

## Task 1：核心数据、关系与兼容
- 先写API验收失败用例：旧课程初始化、profile并发冲突、手动真实跨课关系、旧课程隔离、笔记变化和软删除、迁移与备份。
- 实现共享四模型与Alembic，app/schemas/forest.py，app/forest/service.py，app/api/v1/forest.py（仅profile/relations）；更新备份。
- 核对规格固定接口；局部pytest→全量Ruff/pytest。

## Task 2：自然手绘森林界面
- 先写稳定布局、overview折叠/聚焦、叶子跳转、关系确认等失败测试。
- 实现独立features/forest域：布局/相机/SVG植物/课程面板/关系面板/培养方案导入；api/forest.ts和types；/forest路由、首页/侧边栏/课程入口。
- 按可见课程获取outline而非笔记全文；课程新增位置稳定；相机保留与键盘替代；天然笔触且文字清楚。
- npm test/build与浏览器验证。

## Task 3：培养方案与AI持久任务
- 先写培养方案先预览后确认/失败重试/数据归属/来源校验/幂等/原笔记保护等失败测试。
- app/forest/curriculum.py、app/forest/jobs.py、app/api/v1/forest_imports.py；扩展独立runner和material_worker成功事务自动排队。
- 实现解析/AI结构化校验/候选确认数据，明确本地降级和错误。
- 使用共享模型/契约，不改核心profile/relations实现，核心数据与任务接口固定后集成。

## Task 4：集成、证据与交付
- 路由注册、任务服务互查、旧库及备份兼容、完整浏览器流程/大森林性能；必要发现补回归修复。
- 同步AGENTS.md、agent.md、architecture/api/acceptance/scope/open-source-tools、README与交接。
- 统一完整测试、独立代码审查、只暂存本任务文件；核对身份与密钥过滤，提交推送并创建main目标PR，附到聊天。未验证真实外部模型与真实课程质量单列，不假称完成。