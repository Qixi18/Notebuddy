# 本地运行与备份操作

本地数据库、原文件、派生目录及浏览器视图状态的归属见 [后端调用与业务数据存储契约](backend-data-contract.md)。

## 启动

已有服务占用端口或需要载入更新代码时，可双击 `restart-notebuddy.bat`，或执行 `start-notebuddy.bat -Restart` / `pwsh -NoProfile -File .\scripts\dev.ps1 -Restart`。重启前只结束由本仓库路径和 API/Worker/Vite 启动命令确认归属的进程及其子进程；其他程序占用的端口继续报错，不会被按端口强行清理。`-Check` 始终只检查依赖，即使同时传入 `-Restart` 也不停止服务。

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

## 培养方案导入与恢复

森林的“导入培养方案”支持 PDF、DOCX 或粘贴文本，默认跟随设置中的处理路线，可对本次覆盖。标准路线本地解析，可用模型时分批提取；未配置模型时明确显示本地规则。全程 AI 使用已有页渲染与模型读页服务，扫描 PDF 可直接读页，DOCX 需要本机 Word/LibreOffice 或已配置 Gotenberg；缺少模型配置在入队前拒绝。

任务按冻结路线继续，成功步骤保留；失败后修正模型服务再点“重试解析”。原文件或粘贴来源被改动时必须重新导入。预览可编辑课程代码/学分/学时/必选修，排除行可恢复，显示已知学分合计，与最近20次记录中的已确认方案对比；未包含的旧课程保留。一次最多300门课程，过长资料按学期拆分；不是毕业资格或学分规则判定引擎。

确认后可先查看撤销影响。撤销前在 backups 目录创建 `pre-curriculum-revert-*` 检查点；只回收仍为空的新课程，并恢复未被后续改动的旧属性。有任何版本、内容或使用冲突则整批拒绝，不自动删除后续数据。备份失败时不改课程；旧记录没有快照则无撤销入口。验证时使用合成资料与隔离库，不在正式资料上演练撤销。

## GitHub 分支保护（需仓库管理员执行）

本地文档与 `.githooks/pre-commit` 不构成服务端保护。仓库现有 `.github/workflows/ci.yml`，其 job check 名称配置为 `CI / quality`；需先等待 GitHub Actions 实际运行成功，并确认 GitHub 显示的状态检查名称，再由管理员对 `main` 和 `fix/overall-debug-integration` 配置 Ruleset/branch protection。建议要求 PR review 和该 CI 检查、禁止 force push 与分支删除，并按团队决定限制直接 push；应检查可绕过保护的主体并尽量收窄。当前未核实或更改远端设置，也未确认该检查已在 GitHub 成功。提交签名、线性历史是可选项；启用线性历史前需调整本手册普通 merge 冲突整合协议，避免策略相互矛盾。

如需在服务完全停止后切换当前 `data/`，使用显式替换命令：

```powershell
pwsh -NoProfile -File .\scripts\restore.ps1 -Package -Replace -Checkpoint 'D:\path\to\backup.notebuddy.zip'
```

该命令会先校验包，再把当前 `data/` 复制为同级检查点，最后切换到临时恢复目录。切换失败会尝试恢复原目录；检查点会保留，供人工回滚和核对。命令会拒绝仍有 8000/5173 监听的情况。
