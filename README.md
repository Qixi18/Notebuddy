# NoteBuddy

NoteBuddy 是以课程为中心的学习工作区。用户可以导入资料、整理和编辑笔记，在知识树中定位内容，并基于课程资料进行检索答疑。当前仓库以本地 Web 应用为主要运行形态；Electron 包装仍需完整联调。Agent 规则见 [AGENTS.md](AGENTS.md)，三人协作流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，目录职责见 [模块职责地图](docs/module-map.md)。

## 当前架构基线 / 重大变更

**标准资料处理升级（2026-11-05）**：默认文档上限为 **200 MiB / 2,000 页**，已有配置优先；标准 CPU 路线改进混合扫描 OCR、双栏顺序、矢量图证据、逐页处理及长文本/表格完整性。来源仍为版本化 DocumentIR，正式正文仍经统一 revision/CAS 写入；无数据库迁移。方案见 [ADR-0005](docs/architecture-decisions/ADR-0005-standard-document-completeness.md)（Proposed），限制与验证见 [解析说明](docs/parsing.md) 和 [验收记录](docs/acceptance.md)。

当前正式可编辑 Notebook 正文以 `Notebook.document_json` 为唯一权威源，并通过 revision/CAS 保存。原始资料解析结果、目录、检索块和森林视图属于来源或派生数据，不是第二套正文。架构决策入口见 [ADR 索引](docs/architecture-decisions/README.md)；基线记录 ADR-0001 当前为 Proposed，尚未获协作者审核。任何全局架构变更必须按根目录 [AGENTS.md](AGENTS.md) 公示并同步契约、测试和跨 Agent 影响。

**当前架构公告**：正文、来源解析和派生索引的权威边界见上文及 [架构说明](docs/architecture.md)。两个固定分支及功能分支的 PR 流程见 [协作指南](CONTRIBUTING.md)。整改路线见 [ADR-0002](docs/architecture-decisions/ADR-0002-verified-notebook-assistant-and-file-budget.md)；Notebook/Material 路由职责下沉见 [ADR-0003](docs/architecture-decisions/ADR-0003-service-layer-final-extraction.md)。其余复杂会话、Forest、Knowledge、Courses 用例及历史自动回归记录见 [ADR-0004](docs/architecture-decisions/ADR-0004-remaining-business-use-cases.md)；ADR 仍为 Proposed，等待技术审查。当前主要目录职责见 [模块职责地图](docs/module-map.md)。

## 当前能力与边界

2026-11-08 混合 AI 处理：新上传选择“AI 增强”（API 仍为 `llm`）时默认先本地解析，疑难页交给已预检的视觉模型；成功读取及已验证生成批次可恢复。安装 MinerU 用 `pwsh -NoProfile -File .\scripts\setup.ps1 -WithMinerU`，重跑 setup 会保留已装的 MinerU extra。新上传可用 `NOTEBOOK_LLM_READING_MODE=vision` 回退全页视觉；旧任务快照不变。来源、预算、质量门禁及正文 revision/CAS 保持原路径。方案见 [ADR-0006](docs/architecture-decisions/ADR-0006-hybrid-ai-document-processing.md)（Proposed）；实际验证与限制见 [混合处理交付记录](docs/development/2026-11-08-hybrid-ai-processing.md)，真实材料/模型质量和费用节省仍须分别验收。

- 一门课程可有多本笔记本；笔记按讲次、章节和小节组织，知识树叶子定位到具体笔记小节。课程、资料、笔记、会话及修改记录保存在本地 SQLite。
- 资料上传后进入持久任务队列，由独立执行器解析。解析结果保留来源位置与告警；扫描 PDF 等缺少可提取文字的情况需要检查或启用 OCR。
- Notebook 上传后的初始/增量生成通过质量门禁后可写入正式正文；当前 Agent 答疑不修改正文，旧编辑建议数据与审核 API 暂保留兼容但不由 Agent 新建。
- 课程答疑支持持久会话、资料检索、来源展示与可选的网络搜索。未配置外部模型时存在本地降级路径；降级结果不代表真实模型质量。
- 首页展示近期课程知识树，森林页浏览全部课程。培养方案先预览再确认导入。

产品和验证状态会随开发变化。功能细节见 [架构说明](docs/architecture.md)、[API](docs/api.md)；已执行的检查及尚待验收项见 [验收矩阵](docs/acceptance.md)。当前权威文档入口见 [文档导航](docs/index.md)。

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

已完成环境准备后，也可直接双击仓库根目录的 `start-notebuddy.bat`，同时启动后端、Web 和后台任务执行器；保持窗口打开，启动后访问 `http://localhost:5173`，按 `Ctrl+C` 停止。在命令行执行 `start-notebuddy.bat -Check` 可只检查依赖，不启动服务或迁移数据库。

若上次关闭窗口后服务仍占用端口，或希望加载最新后端代码，可执行 `start-notebuddy.bat -Restart`；它只停止经项目路径与启动命令确认属于本仓库的 API、Worker、Vite 及其子进程，再按正常流程启动，不会按端口盲目结束其他程序。

也可直接双击根目录的 `restart-notebuddy.bat` 完成上述重启。

Windows 下在仓库根目录执行以下两步。首次准备需要本机已有 `uv`、Node.js 22.22.2+（含 npm；锁定的 Web 测试依赖最低要求），或已经放好项目内的 `.runtime/bin/uv.exe` 和 `.runtime/node`。Python 会安装在项目内，不要求预先安装到系统。

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

GitHub Pull Request 和共享/稳定分支推送另运行 [CI 工作流](.github/workflows/ci.yml)，包括静态架构边界检查。该配置不会自动开启分支保护；Required status checks 仍需仓库管理员在 GitHub Ruleset/branch protection 中按实际成功的检查名称配置。PR 信息模板见 [.github/pull_request_template.md](.github/pull_request_template.md)。

## 进一步阅读

- [文档索引](docs/index.md)、[架构说明](docs/architecture.md)、[模块职责地图](docs/module-map.md)
- [后端数据契约](docs/backend-data-contract.md)、[API](docs/api.md)、[资料解析](docs/parsing.md)
- [迁移与恢复](docs/migrations.md)、[运维说明](docs/operations.md)、[安全说明](docs/security.md)
- [架构决策](docs/architecture-decisions/README.md)、[验收矩阵](docs/acceptance.md)
- [协作指南](CONTRIBUTING.md)
