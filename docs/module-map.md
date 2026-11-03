# NoteBuddy 模块职责地图

本文描述当前 `feat/overall-inspection` 工作树中的主要模块职责，帮助协作者定位新代码的归属。它是导航和边界说明，不替代源码、API 契约或数据模型。若与实现不符，以当前源码为准，并在同一修改中修正文档。

## 高频修改文件与协作约束

以下清单只覆盖容易产生多人冲突或跨模块影响的公共入口和数据边界，不是完整文件目录。单人维护的小型改动可按常规流程处理；多人任务若涉及表中任一项，协调人应在开始前分配唯一主编辑者，或明确互不重叠的修改区段、依赖接口和集成顺序。表中“先同步”表示需要通知受影响协作者，不代表该文件由某一固定角色永久拥有。

| 文件或模块 | 主要职责 | 修改注意事项与协作约束 |
| --- | --- | --- |
| `apps/web/src/App.tsx` | `appRoutes`、重定向、错误边界和顶层 Workspace/shell 组合 | 修改前盘点全部路由、旧路径跳转、错误边界和懒加载；router 实例由 `main.tsx` 创建。跨页面任务指定唯一主编辑者，功能页开发者通过独立组件/API提交接入补丁 |
| `apps/web/src/pages/NotebookPage.tsx` | Notebook 页面入口及页面级业务组合 | 保持页面组合职责；先确认对应 Feature/Hook 是否已有状态和 API，避免并行开发者各自重新引入业务状态中心；Notebook 页面跨多人任务指定一名集成负责人 |
| `apps/web/src/api/` | 前端 HTTP 契约、请求函数与类型 | 接口/schema 改动须和后端负责人先对齐路径、字段、可空性、错误及兼容策略；共享 API 类型指定一人集成，调用方同步更新 |
| `apps/backend/app/api/v1/routes.py` | 后端顶层业务 Router 聚合注册 | 只注册模块 Router，不添加业务实现。多人新增路由时由集成负责人统一登记，避免重复注册/前缀 |
| `apps/backend/app/api/v1/notebook.py`、`materials.py` | Notebook 兼容导出入口、Materials 路由聚合与兼容导出 | 新端点应放在对应子路由；仅在确需兼容时改聚合入口。修改前搜索测试、内部导入和外部兼容调用，聚合入口由一人集成 |
| `apps/backend/app/api/v1/notebook_routes/`、`material_routes/` | 按业务群组织的 HTTP 路由 | 按业务域分配子模块；路径、响应模型、状态码和错误映射变化先同步前端 API 调用方及相关 Service 负责人 |
| `apps/backend/app/services/` | 应用用例、跨模块编排和事务边界 | 按垂直业务用例分配文件；服务新增逻辑使用框架无关错误，不依赖 FastAPI Router/HTTP 异常。共享事务或公共服务签名变化先同步调用方 |
| `apps/backend/app/notes/store.py` | Notebook 正文统一写入、revision/CAS 与历史维护 | 正文写入的高风险单点；不得增加平行写入路径。任何并行改动必须由技术把关者先审接口/事务方案，并指定单一主编辑者 |
| `apps/backend/app/schemas/` | 后端请求/响应及数据校验契约 | 公共字段修改前先确定兼容窗口和调用方；协调人维护接口约定，前端 API 类型与文档应在同一切片同步 |
| `apps/backend/app/db/models.py`、`apps/backend/alembic/versions/` | ORM 模型与数据库迁移 | 多人不得并行编辑同一个迁移文件；schema 变化先审 ADR/升级降级策略，迁移文件由一人生成并集成，其他人基于已确认字段开发 |
| `apps/backend/app/document_processing/` | 原始资料解析与 DocumentIR 生成/读取能力 | 维护 Asset/ParseRun/DocumentIR 的来源契约和质量语义，不负责 Notebook 正文存储；涉及格式、质量状态或快照字段时先同步生成、检索和前端调用方 |
| `apps/backend/app/workers/`、`generation/` | 持久任务执行、生成上下文与质量门禁 | 任务状态、重试、取消、幂等键及 revision/CAS 语义需先形成共享约定；避免 API、Worker 和生成逻辑由不同人按不同状态机并行实现 |
| `apps/web/src/styles.css`、`redesign.css` | 全局主题和跨页面样式 | 多页面并行开发时由一人维护全局 token/基底；功能样式优先局部化，避免多个切片同时覆盖公共选择器 |

### 多人修改这些模块时的操作约定

1. 协调人在任务表记录每个切片的负责人、目标分支/worktree、允许修改的路径、验收条件和依赖方；同一文件默认只有一位主编辑者。
2. 若切片需要共享契约，先确定 schema、错误形状、事务/状态语义和 stub，再按“领域/Service → 后端路由/schema → 前端 API/Feature → 页面/全局入口”集成。
3. 公共文件的集成改动由指定负责人完成。其他协作者可先在自己的分支实现局部补丁，交给负责人顺序应用；不得在共享工作区互相覆盖未提交内容。
4. 集成后由非作者交叉审查最终合并差异；协调人收集各切片验证证据，并单独记录尚未验证的跨模块行为。

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
| `api/v1/` | HTTP 路由、请求/响应适配及文件传输 | 新接口按业务路由模块归属。`notebook.py`、`materials.py` 是兼容聚合入口；实际端点在相应 `*_routes/` 子目录。路由不承担 ORM 查询、资源范围规则或应用异常映射 |
| `services/` | 应用用例和跨模块编排，包括事务边界、资源范围检查和服务端业务规则 | 组合数据库与领域能力。Notebook 文档/历史/生命周期/资源、Material 聚合、DocumentIR 兼容读取、Asset 处理任务/预算、上传批次及资源范围查询均有应用服务入口；预期业务错误使用框架无关 `ApplicationError` 并由全局处理器映射。部分读取（例如按需渲染 PDF 页面）会写派生缓存并提交该副作用；其余读取保持只读。服务直接使用 SQLAlchemy，不要求 Repository 层 |
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
