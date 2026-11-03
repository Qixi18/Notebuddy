# NoteBuddy 模块职责地图

本文描述当前 `feat/overall-inspection` 工作树中的主要模块职责，帮助协作者定位新代码的归属。它是导航和边界说明，不替代源码、API 契约或数据模型。若与实现不符，以当前源码为准，并在同一修改中修正文档。

## 仓库顶层

| 路径 | 职责 | 边界 |
| --- | --- | --- |
| `apps/backend` | FastAPI 后端、数据模型、任务执行器和后端测试 | HTTP 接入、应用编排、领域能力与基础设施按职责协作；不因目录相邻而跨层堆放业务逻辑 |
| `apps/web` | React/TypeScript 浏览器客户端 | 页面通过 `api/` 访问后端；页面组合业务 Feature，不直接承担后端持久化或绕过 API 模块请求 |
| `apps/desktop` | Electron 桌面包装 | 复用 Web 与本地服务运行契约；桌面主进程只负责桌面宿主能力 |
| `docs` | 架构、契约、操作、决策和验收资料 | 当前实现说明、提案与历史记录应标明状态及基线 |
| `scripts` | 本地环境、开发、检查、测试等自动化入口 | 命令副作用和数据目录以脚本实现及 README 为准 |
| `.githooks` | 可选的本地 Git 辅助检查 | 不能替代 CI、PR 审查或服务端分支保护 |
| `data` | 本机运行数据目录 | 数据库、上传资料和备份不纳入版本控制 |

## 后端：`apps/backend/app`

| 路径 | 职责 | 放置规则与依赖方向 |
| --- | --- | --- |
| `api/v1/` | HTTP 路由、请求/响应适配、身份与范围解析、HTTP 错误映射 | 新接口按业务路由模块归属。`notebook.py`、`materials.py` 是兼容聚合入口；实际端点在相应 `*_routes/` 子目录。路由不应成为新业务编排的默认位置 |
| `services/` | 应用用例和跨模块编排，包括事务边界及服务端业务规则 | 组合数据库与领域能力。Notebook 文档、关系、建议及资料 DocumentIR 读取已有服务用例；逐步使用框架无关错误，不反向依赖 API Router。部分读请求（例如按需渲染 PDF 页面）会写派生缓存并提交该副作用；其余读取应保持只读。当前部分服务仍直接使用 SQLAlchemy，提取并不等于 Repository 层 |
| `schemas/` | API 与应用边界的数据结构、校验和序列化契约 | 修改公共字段时同步 API 文档及 Web 类型/调用方 |
| `db/` | SQLAlchemy 模型、数据库连接、会话及数据库配置 | 数据库 schema 变化通过新增迁移；不能修改已发布迁移或另造正文存储 |
| `notes/` | Notebook 正文存储、revision/CAS、版本与派生目录能力 | `store.py` 是正式正文写入的统一底层路径；`index.py` 生成派生章节/文本投影 |
| `document_processing/` | 资料解析流水线、解析配置、DocumentIR 和解析质量处理 | 处理原始 Asset/Material；DocumentIR 是来源解析数据，不是 Notebook 正文 |
| `generation/` | 生成上下文、结构与质量校验等生成领域能力 | Worker/应用用例在质量门禁和 revision/CAS 保护下调用；不绕过正文写入路径 |
| `retrieval/` | 对 Notebook、解析资料等来源的范围化检索 | 受服务端课程/Notebook 范围约束；检索结果为派生读取，不成为新的权威内容库 |
| `ai/`、`web_search/` | 模型执行、Notebook 答疑、Agent 读取工具及外部搜索/来源核验能力 | 复用服务端证据和范围契约；外部 Provider 费用与凭据遵循配置、审计和预算边界 |
| `forest/`、`knowledge/` | 知识森林及知识关联的领域逻辑 | 基于课程、Notebook、目录和关系呈现/检索；不复制 Notebook 正文 |
| `workers/` | 持久任务队列的后台执行入口及 Worker 实现 | 任务创建由 API/服务契约发起，异步执行不依赖浏览器进程存活 |
| `parsers/` | 文件格式解析器及解析适配 | 由 Document Processing 调用，不自行创建第二套解析状态或正文路径 |
| `core/` | 后端共享配置、通用错误和跨模块基础能力 | 仅放多个模块确实共享的基础设施，不作为业务杂物目录 |
| `migration/` | Alembic 迁移环境及版本 | 新迁移保持单向、可审查；在隔离数据库验证 |
| `tests/` | 后端单元、集成、契约和边界测试 | 使用隔离临时数据；测试结果须对应明确代码基线和实际执行命令 |

### 后端请求依赖方向

```text
HTTP Client → api/v1 路由 → services 应用用例 → 领域模块 / db 与外部适配
                                  ↓
                           notes/store 正文写入
```

这是逻辑边界，不要求立即新增 Python 顶层目录或 Repository 抽象。路由拆文件本身不表示业务和事务已下沉；尚未迁移的 handler 应在对应垂直用例中渐进处理。

## Web：`apps/web/src`

| 路径 | 职责 | 放置规则 |
| --- | --- | --- |
| `main.tsx`、`App.tsx` | 应用启动、路由对象及顶层 Workspace/页面 shell 组合 | 路由身份、兼容重定向与错误边界属于应用导航；具体业务留给 Feature |
| `pages/` | URL 对应的页面入口和页面级组合 | 不把整项业务状态机、所有 API 请求和持久化规则塞入单一页面 |
| `features/` | 按业务组织的功能、状态、Hooks 和专属组件 | Notebook 编辑、上传/生成、森林、答疑等能力应归入明确 Feature；跨 Feature 复用需审慎抽公共接口 |
| `api/` | 按领域组织的 HTTP 请求、请求/响应映射及 API 类型 | 页面和 Feature 经此层调用后端，不直接散布 fetch/HTTP 细节 |
| `components/` | 跨业务复用的通用 UI 组件 | 保持业务无关；只在确有复用时提升，避免单页组件提前通用化 |
| `utils/` | 无明确业务归属的纯工具 | 领域规则应留在对应 Feature 或领域模块 |
| `styles.css`、`redesign.css` 及样式文件 | 全局主题、布局基础和组件样式 | 业务局部样式尽量贴近所属组件，遵循现有主题与响应式约定 |
| `types.ts` | 暂存公共/共享类型 | 新增领域类型优先放在所属 Feature/API 域，避免持续扩大全局类型入口 |
| `tests/`、`**/*.test.*` | 页面导航、组件、Feature 和 API 行为测试 | 覆盖用户可见交互与契约；单测不能替代真实浏览器验收 |

### Web 请求依赖方向

```text
Router → Page → Feature / Hook → api/ → Backend API
             ↘ components/（共享展示组件）
```

当前 Notebook 页面已将文档、资源和生成等职责拆到对应 Hooks/Feature；继续拆分应由业务职责和状态边界驱动，不以文件行数作为验收标准。

## 正文、资料与派生数据边界

- 唯一正式可编辑正文：`Notebook.document_json`；写入须使用现有 `document_revision` / CAS、历史版本和统一存储逻辑。
- 来源解析：Asset/Material 关联的 ParseRun 与 DocumentIR，保留原始资料的解析版本、结构、位置及质量状态。
- 派生数据：`NotebookSection` 目录/文本投影、检索块、知识森林导航索引；可按权威来源重建，不是正文。
- 兼容/历史：旧 Note、NoteRevision、旧 API 和历史建议数据仅保留已明确的兼容、迁移、审计或历史用途。增加新业务前先确认当前路由与调用方。

详细数据读写和兼容接口以 [后端数据契约](backend-data-contract.md)、[API 文档](api.md) 及源码为准。架构提案状态见 [ADR 索引](architecture-decisions/README.md)。

## 新业务落点速查

1. 确认业务数据的权威来源和课程/Notebook 范围，不新增第二套存储路径。
2. 后端用例放在相应领域模块与 `services/`，路由只承担 HTTP 接入和映射；共享契约同时更新 schemas、前端 `api/` 与文档。
3. Web 页面负责组合，对应业务状态和交互归属 Feature；通用 `components/` 仅承载跨业务 UI。
4. 涉及数据库、正文、DocumentIR 或跨模块公共契约时，先依 [ADR 流程](architecture-decisions/README.md)记录方案并审查。
5. 按改动范围运行检查并记录结果；涉及真实材料、模型费用、浏览器或迁移的验收须明确区分自动化与人工证据。
