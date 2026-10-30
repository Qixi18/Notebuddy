# 本地数据库迁移与检查点

数据库由 `apps/backend/migrations/` 中的 Alembic 版本管理。启动 API 和资料执行器都会调用 `app.db.migrate.migrate_database()`；`scripts/dev.ps1` 在启动进程前先同步执行一次迁移。旧版未登记 Alembic 的数据库经兼容基线检查后登记初始版本，再升级到当前版本。若表/列结构不在已支持范围内，启动会停止，保留原库供人工排查。

迁移前会在 `data/backups/pre-migration-*` 建立包含 SQLite 在线快照、原文件和 SHA-256 清单的检查点并验证完整性。首次阶段一开发前的检查点在 `data/backups/phase1-20261006`（仅此工作区的本地数据，不提交 Git）。删除课程或资料前也建立 `pre-delete-*` 检查点。检查点不含 `.env`、密钥或派生索引。

## 操作

在仓库根目录使用 PowerShell 7 执行：

```powershell
pwsh -NoProfile -File .\scripts\backup.ps1
pwsh -NoProfile -File .\scripts\restore.ps1 -Checkpoint 'D:\path\to\checkpoint' -Destination 'D:\path\to\empty-data-dir'
```

普通恢复脚本只写入空目录，不替换当前 `data/`。阶段四也提供显式的 `pwsh -NoProfile -File .\scripts\restore.ps1 -Package -Replace -Checkpoint <包>` 路径：它要求服务停止，先保留同级检查点，再切换已验证的临时目录；失败时恢复原目录。阶段四的 `.notebuddy.zip` 包还会在导入预览和恢复前校验包版本、路径、文件哈希及 SQLite integrity。

迁移验证应覆盖新库、已存在的无版本旧库、再次启动、失败回滚和保留用户笔记/来源。先按 README 运行 `scripts/setup.ps1` 准备项目环境，再从 `apps/backend` 用 `& .\.venv-document\Scripts\python.exe -m pytest -q` 运行隔离目录中的相关回归。不得将真实用户库传给测试或迁移命令。迁移或删除发生异常时，不要删除检查点，也不要反复手工执行 `ALTER TABLE`。
