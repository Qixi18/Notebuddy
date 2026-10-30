# 本地运行与备份操作

本地数据库、原文件、派生目录及浏览器视图状态的归属见 [后端调用与业务数据存储契约](backend-data-contract.md)。

## 启动

Windows 使用 PowerShell 7，从仓库根目录执行 `pwsh -NoProfile -File .\scripts\dev.ps1 -Check` 检查，再用 `pwsh -NoProfile -File .\scripts\dev.ps1` 启动。脚本启动前检查端口并迁移 SQLite，再启动 API、任务执行器和 Vite；服务进程绑定本机 `127.0.0.1:8000`、`127.0.0.1:5173`，浏览器访问使用 `http://localhost:5173`，退出时脚本结束自身子进程。迁移意味着必须确认当前 `NOTEBOOK_DATA_DIR` 指向预期的本地库；多个实例不能无控制地并发写同一 SQLite。手动运行只用于调试，且必须同时启动 Worker。环境准备和完整命令见 [README](../README.md)。

配置诊断页和 `GET /api/v1/config/provider-calls` 会显示脱敏的外部服务调用记录，包括状态、耗时、用量和可选的费用估算。费用估算只有在 `.env` 配置 `DEEPSEEK_*_COST_PER_MILLION` 后才会出现；记录不保存请求正文、密钥或完整课件。

## 备份

阶段一检查点仍可用：`pwsh -NoProfile -File .\scripts\backup.ps1`。阶段四完整包使用：

```powershell
pwsh -NoProfile -File .\scripts\backup.ps1 -Package
```

包包含 SQLite 一致性快照、课程原文件、哈希清单和派生索引说明，不包含 `.env`、密钥和缓存凭据。API 传入 `course_id` 时生成该课程范围的包；不传则生成整个本地工作区包。可从仓库根目录用 `& .\apps\backend\.venv-document\Scripts\python.exe -m app.services.backup preview <包路径>` 检查包。

## 恢复

恢复只写入空目录，避免未经确认替换当前数据：

```powershell
pwsh -NoProfile -File .\scripts\restore.ps1 -Package -Checkpoint <包路径> -Destination <空目录>
```

恢复前会校验路径、包版本、文件数量、哈希和 SQLite 完整性。恢复后再按 README 启动服务，并抽查课程、原文件、笔记版本、来源、知识树和会话。

首页的“备份检查与恢复”面板可以选择 `.notebuddy.zip`，先展示课程、资料、文件数量、哈希错误和同名文件冲突，再确认恢复到隔离目录。该入口不会替换当前数据；如需切换正式数据目录，先保留检查点并按干净目录演练。

## GitHub 分支保护（需仓库管理员执行）

本地文档与 `.githooks/pre-commit` 不构成服务端保护，本仓库本轮未修改 GitHub 设置。管理员可对 `main` 和 `feat/debug-integration` 分别建立 Ruleset/branch protection：禁止 force push 和分支删除；按团队决策限制直接 push，要求 PR review；仅在 CI 实际存在并确认状态检查名称后，设置 required checks。检查可绕过保护的主体并尽量收窄。提交签名、线性历史是可选项；启用线性历史前需调整本手册普通 merge 冲突整合协议，避免策略相互矛盾。当前没有核实 CI required check 名称，不要凭空配置。

如需在服务完全停止后切换当前 `data/`，使用显式替换命令：

```powershell
pwsh -NoProfile -File .\scripts\restore.ps1 -Package -Replace -Checkpoint 'D:\path\to\backup.notebuddy.zip'
```

该命令会先校验包，再把当前 `data/` 复制为同级检查点，最后切换到临时恢复目录。切换失败会尝试恢复原目录；检查点会保留，供人工回滚和核对。命令会拒绝仍有 8000/5173 监听的情况。
