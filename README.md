# NoteBuddy

NoteBuddy 是以课程为中心的学习工作区。用户可以导入资料、整理和编辑笔记，在知识树中定位内容，并基于课程资料进行检索答疑。当前仓库以本地 Web 应用为主要运行形态；Electron 包装仍需完整联调。Agent 入口见 [AGENTS.md](AGENTS.md)，详细规则见 [agent.md](agent.md)。

## 当前架构基线 / 重大变更

当前正式可编辑 Notebook 正文以 `Notebook.document_json` 为唯一权威源，并通过 revision/CAS 保存。原始资料解析结果、目录、检索块和森林视图属于来源或派生数据，不是第二套正文。架构决策入口见 [ADR 索引](docs/architecture-decisions/README.md)；基线记录 ADR-0001 当前为 Proposed，尚未获协作者审核。任何全局架构变更必须按根目录 [AGENTS.md](AGENTS.md) 公示并同步契约、测试和跨 Agent 影响。

**整改提案（Proposed，待审）**：按 [ADR-0002](docs/architecture-decisions/ADR-0002-verified-notebook-assistant-and-file-budget.md) 与 [实施盘点](implementation-inventory.md) 分批收敛 Notebook 答疑证据门禁、只读正文、未分类会话契约、视觉模型能力预检、单文件 CNY 预算及共享 Workspace。上述内容是开发目标，不代表已实现或验收；实施基线为 2026-11-01 fetch 后的 `feat/overall-inspection`。

**实施进度（2026-11-01）**：A1 会话迁移与旧 Note 答疑入口清理已完成并推送，提交 `0b0c033`；A2 Notebook 第一源、DocumentIR/Web 主张核验、核验后 SSE、B1 视觉模型独立配置与图片能力预检，以及 B2 文件级 10.00 CNY 预算账本，均已在本地实现并通过自动回归。C1/C2 已把课程与未分类 URL 接入同一 `NotebookPage`、统一正文/保存/草稿/历史/附件/AI Bridge，并移除旧未分类页面编排，保留旧 URL。D 已将生成任务创建逻辑下沉到 Application Service，完整 `notebook.py` 拆分仍未完成。当前所有本轮改动仅在本地工作树，未提交、未推送。A2 使用迁移 `a7c4d2e91b60`，B2 使用迁移 `b6e1a9d420fc`。本轮最终完整自动回归：后端 463 passed / 4 skipped，Web navigation 52 passed、Vitest 80 files / 412 passed，Web/Desktop 构建通过；D 服务调整后全量脚本也通过。真实供应商/真实材料和浏览器人工验收未执行；ADR-0002 保持 Proposed，不代表整体规划已全部完成。

## 当前能力与边界

- 一门课程可有多本笔记本；笔记按讲次、章节和小节组织，知识树叶子定位到具体笔记小节。课程、资料、笔记、会话及修改记录保存在本地 SQLite。
- 资料上传后进入持久任务队列，由独立执行器解析。解析结果保留来源位置与告警；扫描 PDF 等缺少可提取文字的情况需要检查或启用 OCR。
- Notebook 上传后的初始/增量生成通过质量门禁后可写入正式正文；当前 Agent 答疑不修改正文，旧编辑建议数据与审核 API 暂保留兼容但不由 Agent 新建。
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

Windows 下在仓库根目录执行以下两步。首次准备需要本机已有 `uv`、Node.js 22.12+（含 npm），或已经放好项目内的 `.runtime/bin/uv.exe` 和 `.runtime/node`。Python 会安装在项目内，不要求预先安装到系统。

```powershell
pwsh -NoProfile -File .\scripts\setup.ps1
pwsh -NoProfile -File .\scripts\dev.ps1
```

`setup.ps1` 可重复执行：优先使用项目内运行时，缺少时复制本机已有的 UV/Node；使用锁文件安装后端、Web 和 Desktop 依赖。后端标准环境是 `apps/backend/.venv-document`，包含 PyMuPDF、fonttools 及 CPU RapidOCR；RapidOCR 的 ONNX 模型随包留在该环境内。Python 安装使用 `--no-bin --no-registry`，不改系统 PATH、Python 注册表或已有 `.env`。首次安装需要联网下载依赖。

可用 `-UvPath <uv.exe>`、`-NodeDirectory <Node安装目录>` 指定已有运行时，`-PythonVersion 3.12` 选择 Python；已有前端依赖时可加 `-SkipWeb -SkipDesktop`。运行时、UV/npm/Electron 下载缓存及安装日志都在 `.runtime`，不提交到 Git。安装失败会返回非零退出码并给出日志路径。

启动前也可只检查依赖，不开端口、不迁移数据库：

```powershell
pwsh -NoProfile -File .\scripts\dev.ps1 -Check
```

`dev.ps1` 使用 `.venv-document` 与项目内 Node；依赖不完整时提示重新执行 setup。正式启动会先迁移数据库，再启动资料执行器、API 与 Web 服务。浏览器访问 `http://localhost:5173`；健康检查为 `http://localhost:8000/api/v1/health`。启动日志在 `data/logs/dev-日期-进程号`。保持脚本运行以处理上传任务，按 `Ctrl+C` 只结束该脚本启动的服务；端口已被使用时直接退出。

如需打开 Electron，在上述服务运行期间另开终端执行：

```powershell
$env:Path = "$PWD\.runtime\node;$env:Path"
$env:ELECTRON_CACHE = "$PWD\.runtime\cache\electron"
$env:NOTEBOOK_DESKTOP_DEV_URL = 'http://127.0.0.1:5173'
& .\.runtime\node\node.exe .\.runtime\node\node_modules\npm\bin\npm-cli.js --prefix apps/desktop run dev
```

单独启动后端服务时，在 `apps/backend` 使用 `& .\.venv-document\Scripts\python.exe -m app.workers.runner` 和 `& .\.venv-document\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。缺少执行器时，上传任务会停留在队列中。

## 可选配置

尚无 `.env` 时，复制根目录 `.env.example` 为 `.env`，按需填写 `DEEPSEEK_API_KEY`、`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` 和 `TAVILY_API_KEY`。已有 `.env` 请直接编辑，避免覆盖密钥。没有外部服务配置时仍可运行本地降级功能。示例配置启用 `NOTEBOOK_OCR_ENABLED=true`、`NOTEBOOK_OCR_ENGINE=rapidocr`；已有配置由用户决定是否开启，setup 不会更改它。OCR 页数和超时限制也在示例中。

本地单用户设置面板可写入部分密钥；共享或远程部署前应关闭此能力或启用口令，并单独完成身份、数据隔离和密钥管理设计。不要提交 `.env`、`data/` 或真实课件。配置和安全边界见 [安全说明](docs/security.md)。

## 检查

```powershell
pwsh -NoProfile -File .\scripts\test.ps1
```

该命令依次运行后端 ruff、pytest、前端行为测试及生产构建、Desktop 主进程构建，任一步失败立即退出。优先使用项目内 Python/Node，日志在 `.runtime/logs/test-*.log`。`-Check` 仅检查测试依赖。

完整测试连同真实本地 OCR 模型验证：

```powershell
$env:NOTEBOOK_RUN_REAL_OCR = '1'
pwsh -NoProfile -File .\scripts\test.ps1
# 等价的一步命令：pwsh -NoProfile -File .\scripts\test.ps1 -RealOcr
```

后端测试会使用独立临时数据目录，不改用户资料。脚本自身的安装、缓存和失败退出行为可单独验证；此回归使用隔离目录与假安装命令，不联网安装、不开服务端口：

```powershell
pwsh -NoProfile -File .\scripts\tests\local-environment.test.ps1 -NodePath .\.runtime\node\node.exe -PythonPath .\apps\backend\.venv-document\Scripts\python.exe
```

也可在 `apps/backend` 用 `& .\.venv-document\Scripts\python.exe -m ruff check app tests`、`& .\.venv-document\Scripts\python.exe -m pytest` 运行单项检查。自动检查不能代替真实课件、浏览器流程、外部模型与部署验收；记录实际验证范围并对照 [验收矩阵](docs/acceptance.md)。

## 进一步阅读

- [软件工程文档](docs/软件工程文档/README.md)：需求分析、概要设计、需求说明和教学模板。
- [文档索引](docs/index.md)、[架构说明](docs/architecture.md)、[API](docs/api.md)
- [资料解析](docs/parsing.md)、[来源与证据](docs/evidence.md)、[迁移与恢复](docs/migrations.md)
- [运维说明](docs/operations.md)、[仓库协作指南](agent.md)
