# NoteBuddy

NoteBuddy 是以课程为中心的学习工作区。用户可以导入 PPTX、PDF、DOCX，按讲次整理和编辑笔记，在知识树中定位小节，并基于课程资料进行检索答疑。当前仓库以本地 Web 应用为主要运行形态；Electron 包装仍需完整联调。公共开发约定见 [agent.md](agent.md)。

## 当前能力与边界

- 一门课程可有多本笔记本；笔记按讲次、章节和小节组织，知识树叶子定位到具体笔记小节。课程、资料、笔记、会话及修改记录保存在本地 SQLite。
- 资料上传后进入持久任务队列，由独立执行器解析。解析结果保留来源位置与告警；扫描 PDF 等缺少可提取文字的情况需要检查或启用 OCR。
- 笔记支持用户编辑、版本与锁定保护。AI 修改以建议形式供用户审查；课程内整合与跨课程关系保留来源和版本约束。
- 课程答疑支持持久会话、资料检索、来源展示与可选的网络搜索。未配置外部模型时存在本地降级路径；降级结果不代表真实模型质量。
- 首页展示近期课程知识树，森林页浏览全部课程。培养方案先预览再确认导入。

产品和验证状态会随开发变化。功能细节见 [架构说明](docs/architecture.md)、[API](docs/api.md) 和 [范围变化](docs/scope-changes.md)；已执行的检查及尚待验收项见 [验收矩阵](docs/acceptance.md)。历史设计和交接记录位于 [docs/superpowers](docs/superpowers) 与 [docs/handoffs](docs/handoffs)，其中的旧方案不自动代表当前行为。

## 目录

| 路径 | 内容 |
| --- | --- |
| `apps/web` | React、TypeScript、Vite 前端 |
| `apps/backend` | FastAPI、SQLite、Alembic、解析与任务执行器 |
| `apps/desktop` | Electron 桌面包装 |
| `scripts` | 本地启动、检查和辅助脚本 |
| `docs` | 架构、接口、专项设计与验收记录 |
| `data` | 本地数据库、上传资料和备份；不提交到 Git |

## 本地启动

需要 Python 3.12+、`uv`、Node.js 22.12+ 和 `npm`。在仓库根目录执行：

```powershell
cd apps/backend
uv sync --locked
cd ../web
npm ci
cd ../..
./scripts/dev.ps1
```

脚本先检查数据库迁移，再启动资料执行器、API 与 Web 开发服务。浏览器访问 `http://127.0.0.1:5173`；API 健康检查为 `http://127.0.0.1:8000/api/v1/health`。保持脚本运行以处理上传任务，按 `Ctrl+C` 结束。

如需分别启动服务，先在 `apps/backend` 执行 `uv run python -m app.workers.runner`，再运行 `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`；最后在 `apps/web` 运行 `npm run dev -- --host 127.0.0.1`。缺少执行器时，上传任务会停留在队列中。

## 可选配置

复制根目录 `.env.example` 为 `.env`，按需填写 `DEEPSEEK_API_KEY`、`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` 和 `TAVILY_API_KEY`。没有外部服务配置时仍可运行本地降级功能。OCR 默认关闭，相关开关与限制也在 `.env.example` 中。

本地单用户设置面板可写入部分密钥；共享或远程部署前应关闭此能力或启用口令，并单独完成身份、数据隔离和密钥管理设计。不要提交 `.env`、`data/` 或真实课件。配置和安全边界见 [安全说明](docs/security.md)。

## 检查

```powershell
./scripts/test.ps1
```

也可按改动范围分别在 `apps/backend` 执行 `uv run ruff check app tests`、`uv run pytest`，在 `apps/web` 执行 `npm test`、`npm run build`，在 `apps/desktop` 执行 `npm run build:main`。自动检查不能代替真实课件、浏览器流程、外部模型与部署验收；记录实际验证范围并对照 [验收矩阵](docs/acceptance.md)。

## 进一步阅读

- [软件工程文档](docs/软件工程文档/README.md)：需求分析、概要设计、需求说明和教学模板。
- [文档索引](docs/index.md)、[架构说明](docs/architecture.md)、[API](docs/api.md)
- [资料解析](docs/parsing.md)、[来源与证据](docs/evidence.md)、[迁移与恢复](docs/migrations.md)
- [运维说明](docs/operations.md)、[仓库协作指南](agent.md)
