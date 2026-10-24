# NoteBuddy Vercel 多用户部署设计

日期：2026-10-18。状态：设计已确定，登录链路已有基础代码；租户隔离、持久存储、后台任务与云端资源尚未完成。

## 目标与当前故障

线上 `notebuddy-beta.vercel.app` 已能返回静态首页，但 `/api/v1/courses` 与 `/api/v1/forest` 返回 Vercel `NOT_FOUND`。当前 Vite 的 `/api` 代理仅在本地开发服务器运行。目标是前端与后端都部署在 Vercel，用户登录后各自拥有独立课程、资料、笔记、会话和备份。

## 目标架构

| 层 | 选型 | 作用 |
| --- | --- | --- |
| Web | 现有 Vite/React，Vercel 项目根目录 `apps/web` | 页面与 `/api/*` 到 API 项目的同源代理 |
| 身份 | Clerk React + 后端验证会话 JWT | 登录、注册和稳定用户 ID；前端显示状态不能代替后端鉴权 |
| API | 现有 FastAPI，Vercel Python Function | 无状态 HTTP 请求；不在请求生命周期中跑后台任务 |
| 业务库 | Vercel Marketplace 的 PostgreSQL（优先 Neon） | 课程、笔记、任务、会话、用户归属与版本 |
| 原资料与备份 | 私有 Vercel Blob | 上传文件、派生文件和备份；每个对象的 key 含用户 ID，读取前仍需查数据库归属 |
| 后台任务 | Vercel Daemon，单实例起步 | 消费数据库待处理任务并运行现有解析/森林任务；故障恢复基于 DB 租约而非本机文件锁 |

前端和 API 分成两个 Vercel 项目，避免依赖仍需项目准入的 Services 私有 Beta。API 的 Python Function 与 Daemon 可共享同一项目配置。Daemon 当前是公开 Beta，正式部署前须在目标 `qixi18` 空间核验可用性和费用；若不可用，不能把本地 worker 直接放进普通 Function 假装常驻。

## 必须完成的代码迁移

1. **租户边界**：`Course`、尚未生成课程的 `CurriculumImport`、备份记录和提供商调用记录增加 `owner_id`。课程列表、森林、跨课关系、回收站、资料、笔记、会话、设置与备份入口均按认证用户过滤。所有按 ID 读写的接口都要检查归属；前端隐藏链接不是权限控制。跨课程关系的两端必须属于同一用户。旧本地 SQLite 数据迁移时由用户显式指定归属，不能自动归给第一个登录者。
2. **PostgreSQL**：给 SQLAlchemy 增加可配置的 PostgreSQL 连接与连接池。迁移 SQLite 方言的 upsert、部分索引、文件快照与 Alembic 迁移。生产环境只由单独迁移步骤升级数据库，不在每个 Function 冷启动时执行迁移。
3. **文件持久化**：上传仍进行格式/大小校验，原文件写入私有 Blob；处理任务在临时目录下载并解析；所有持久派生文件与备份写回 Blob。删除和恢复需要处理数据库与 Blob 的一致性。不能把 `/tmp` 或 Function 工作目录当作永久磁盘。
4. **后台任务**：把现有文件锁替换成数据库原子领取和租约/心跳。Daemon 退出、重复领取和超时重试要有回归。API 只登记任务。
5. **登录**：前端登录态获取会话 token 并附到 API 请求。FastAPI 验证 JWT 签名、发行者、时效和授权来源，获取 `sub` 作为稳定用户 ID。公开健康检查不泄露业务状态；其余业务接口无 token 返回 401。
6. **部署与验收**：配置 Web 项目的 API 地址和 Clerk 公钥，API 项目的 Clerk 校验材料、数据库、Blob 等服务端变量。分别验证未登录 401、用户 A/B 数据互不可见、上传到任务完成、重启后数据保留、旧 SQLite 导入、备份恢复和真实模型调用。

## 发布门槛

当前本地代码没有上述多用户与无状态存储能力，不能仅通过添加路由重写发布给多人使用。前端已接入 Clerk 的登录组件与 Bearer token 传递；后端已接入 Clerk token 验证骨架，但云端模式在启动时明确拒绝，直到租户隔离与持久化完成。完成迁移及隔离测试后才切换生产域名。

Vercel CLI 已以 `qixi18` 空间读取 `notebuddy`：生产部署 `dpl_21SXR5Erz5iSy4DPvSdD43CXup4g` 为 Ready，项目根目录是 `apps/web`、框架是 Vite，当前没有项目环境变量。Vercel 连接器仍返回 403，CLI 只读访问可用。生产站点的 `/api/v1/courses` 与 `/api/v1/forest` 均返回 `X-Vercel-Error: NOT_FOUND`，是前端部署没有 API 目标的直接证据。
