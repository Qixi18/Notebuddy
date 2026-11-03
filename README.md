# NoteBuddy

NoteBuddy 是以课程为中心的学习工作区。用户可以导入资料、整理和编辑笔记，在知识树中定位内容，并基于课程资料进行检索答疑。当前仓库以本地 Web 应用为主要运行形态；Electron 包装仍需完整联调。Agent 入口见 [AGENTS.md](AGENTS.md)，详细规则见 [agent.md](agent.md)。

## 当前架构基线 / 重大变更

当前正式可编辑 Notebook 正文以 `Notebook.document_json` 为唯一权威源，并通过 revision/CAS 保存。原始资料解析结果、目录、检索块和森林视图属于来源或派生数据，不是第二套正文。架构决策入口见 [ADR 索引](docs/architecture-decisions/README.md)；基线记录 ADR-0001 当前为 Proposed，尚未获协作者审核。任何全局架构变更必须按根目录 [AGENTS.md](AGENTS.md) 公示并同步契约、测试和跨 Agent 影响。

**整改提案（Proposed，待审）**：按 [ADR-0002](docs/architecture-decisions/ADR-0002-verified-notebook-assistant-and-file-budget.md) 与 [实施盘点](implementation-inventory.md) 分批收敛 Notebook 答疑证据门禁、只读正文、未分类会话契约、视觉模型能力预检、单文件 CNY 预算及共享 Workspace。上述内容是开发目标，不代表已实现或验收；实施基线为 `feat/overall-inspection`。2026-11-03 复核新增运行时路由与业务边界整改提案：Web 页面现已迁入 `createBrowserRouter` 的嵌套路由对象，Notebook 桥接与侧栏跳转有组件级回归覆盖；Notebook API 文件虽已按功能拆分，handler 中仍有直接数据库事务。后续继续补充路由错误边界，并按垂直用例推进 API/service 分层。ADR 继续保持 Proposed，需协作者审核后才能视为已接受架构。

**实施进度（2026-11-03 复核）**：此前 A1/A2、B1/B2、C1/C2 与 D 第一阶段完成情况见 ADR-0002 的实施记录。后续 S1–S7 在工作树记录了 QA 隔离、预算验收、Notebook hook 拆分及 `notebook_routes/*` 路由文件拆分；当前代码已有 Notebook OpenAPI 契约快照与路由重复/反向依赖检查。该拆分不代表 handler 已与数据库事务/业务编排分层。Notebook 正文保存、历史恢复及图片所有权规则现统一由 `app/services/notebook_document.py` 编排，并继续通过 `notes/store.py` 的唯一 CAS 写入路径落库；章节重排与阅读位置 CAS 也有独立 application service。Web `appRoutes` 现由 `main.tsx` 直接交给 `createBrowserRouter`，嵌套 `<Routes>` 通配包装已移除，旧路径与重定向保留并有路由匹配回归。当前分支含未提交改动；本轮按要求未启动服务或运行测试。ADR-0002 保持 Proposed。

**本轮 S8 实施（2026-11-03，待评估）**：Document Processing 配置实现位于 `app/document_processing/config.py`，解析 Service 和调用端依赖配置模块，旧 `routes.py` 仅保留兼容重导出；Notebook 生命周期变更、建议审核、附件/封面资源写入和删除保护规则下沉至 application services。Notebook 删除统一检查资料、图片和生成任务；图片 Worker 只在终态记录 `finished_at`。前端修复旧 Notebook 路径映射，补充全局及关键页面错误边界，拆分侧栏/导航保护/助手坞控制器，并延迟加载 Notebook、森林、答疑和助手坞及重型编辑器。PPTX/DOCX 标为受限兼容格式，PDF 与独立图片资源按现有质量契约处理。整体改动待用户评估，ADR-0002 仍为 Proposed。

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

`setup.ps1` 可重复执行：优先使用项目内运行时，缺少时复制本机已有的 UV/Node；使用锁文件安装后端、Web 和 Desktop 依赖。后端标准环境是 `apps/backend/.venv-document`，包含 PyMuPDF、fonttools 及 CPU RapidOCR；RapidOCR 的 ONNX 模型随包留在该环境内。PaddleOCR 与 MinerU 是可选本地组件；启用 `NOTEBOOK_OCR_ENGINE=auto` 时优先使用 PaddleOCR，未安装时回退到 RapidOCR。Python 安装使用 `--no-bin --no-registry`，不改系统 PATH、Python 注册表或已有 `.env`。首次安装需要联网下载依赖。

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

尚无 `.env` 时，复制根目录 `.env.example` 为 `.env`，填写要使用的模型服务 API Key；如启用文档付费处理，还要按供应商当前费率补齐模型价格和有效汇率。Embedding 与 Tavily 是可选服务，只有启用对应能力时才需要配置。已有 `.env` 请直接编辑，避免覆盖密钥。未设置的本地地址、端口、OCR 和解析器参数使用程序默认值；没有外部服务配置时仍可运行本地降级功能。示例中的空价格来源或零价格会让付费调用按设计停止，避免未定价调用。

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
