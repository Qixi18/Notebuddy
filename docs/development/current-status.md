# 当前开发状态

## 基线

- 记录日期：2026-11-03
- 当前治理分支：`feat/overall-inspection`
- 本次阶段三、四开发起始基线：`740c6f3`（开始时 HEAD；以当前 Git 状态为准）
- 日常共享集成基线：`feat/debug-integration`
- 产品稳定分支：`main`
- 全局 Notebook 架构提案 ADR-0001/ADR-0002：仍为 Proposed，须按 ADR 记录完成协作者审查后才能调整状态。

## 已落地的工程治理能力

- 根目录 Agent 规则与人员协作规则已分离为 `AGENTS.md` 和 `CONTRIBUTING.md`；协作指南规定分支职责、任务角色和 L1/L2/L3 审查级别。
- `docs/module-map.md` 描述当前主要目录职责、依赖方向及正文/来源/派生数据边界。
- `.github/workflows/ci.yml` 定义 Windows CI：锁定环境安装、架构边界检查，以及 `scripts/test.ps1` 中的 Ruff、Pytest、Web 测试/生产构建、Desktop 主进程构建。
- `scripts/check_architecture_boundaries.py` 静态检查 API 直写正文、正文唯一底层写入入口、改动 Service 对 FastAPI 的依赖、兼容聚合路由注册和改动页面直接 `fetch`。
- `.github/pull_request_template.md` 收集任务角色、等级、影响、验证证据和合并前检查项。
- 本目录建立了状态、路线图、日志规则和任务模板；本次治理工作记录在 `logs/2026/DEV-001-engineering-governance.md`。
- 后续垂直分层增量：Notebook 正文/排序/阅读位置、关系、建议服务已统一使用 `ApplicationError`；关系列表和建议列表由 Service 负责查询/装配；资料 DocumentIR 查询、coverage/evidence、渲染路径解析及解析结果组装位于 `services/document_reads.py`，HTTP 文件响应保留在 Route。PDF 按需渲染会写入派生页面缓存并提交。Quiz Service 仍有 FastAPI 耦合，本轮没有修改。

## 尚未证实或尚未完成

- CI 尚未在 GitHub Actions 实际运行；在首次成功运行前，不将其记录为已通过的状态检查。
- GitHub `main` 与 `feat/debug-integration` 的 Ruleset/branch protection、required check 名称、审查要求、禁止强推/删除等设置尚未通过管理员界面核实或配置。本地仓库文件不会自动启用远端保护。
- 当前架构检查是静态规则的第一版，不能证明任意业务模块都满足完整分层；规则需随实际反例逐步扩展。
- 本次没有把所有 API 路由迁移到 Service，也没有隔离 SQLAlchemy Session/事务；剩余领域需按垂直用例逐步收敛。
- 本次没有执行产品测试套件、启动服务、运行真实资料或调用付费模型；当前分层增量尚无回归通过证据。
- 完整业务回归、浏览器人工验收及真实 PDF/图片/模型质量证据，仍按 `docs/acceptance.md` 和 ADR-0002 对应记录跟踪。
