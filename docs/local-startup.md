# 本地启动说明

- 适用分支：`feat/agent-dialogue`
- 环境：Windows 10/11，PowerShell 5.1 或 7
- 服务：后端 API `127.0.0.1:8000`、前端 `127.0.0.1:5173`、资料执行器（无端口）
- 最近验证：2026-10-20，三端均可启动，前端代理到后端返回 200

## 1. 环境要求

| 组件 | 要求 | 检查命令 |
| --- | --- | --- |
| Node.js | ≥ 22.12 | `node --version` |
| npm | 随 Node 安装 | `npm --version` |
| Python | 3.12（仓库自带 `.venv`） | `apps\backend\.venv\Scripts\python.exe --version` |
| uv | 可选，仅首次装依赖需要 | `uv --version` |

依赖目录已存在时可以跳过安装：`apps/backend/.venv`、`apps/web/node_modules`。

## 2. 首次准备（新克隆或依赖缺失时）

```powershell
cd D:\notebuddy_main\Notebuddy\apps\backend
uv sync --locked

cd ..\web
npm ci
```

如果终端提示 `uv` 不是可识别的命令，但文件存在于 `C:\Users\<用户名>\.local\bin\uv.exe`，可以直接用完整路径，或把该目录加入 PATH 后重开终端。

## 3. 日常启动（推荐，三终端）

必须三个进程都起来。少启动执行器时，上传的资料会一直停在“等待处理”。

### 终端 1：后端 API

```powershell
cd D:\notebuddy_main\Notebuddy\apps\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 终端 2：资料执行器

```powershell
cd D:\notebuddy_main\Notebuddy\apps\backend
.\.venv\Scripts\python.exe -m app.workers.runner
```

### 终端 3：前端

```powershell
cd D:\notebuddy_main\Notebuddy\apps\web
npm run dev
```

浏览器打开：<http://127.0.0.1:5173>

使用 `.venv` 里的 Python 可以绕开 `uv` 不在 PATH 的问题；如果 `uv` 正常可用，把上面两处 `.\.venv\Scripts\python.exe` 换成 `uv run` 也可。

### 3.1 让服务脱离当前终端常驻（可选）

在 IDE 会话里用后台任务启动的服务，通常在会话结束或一段时间后被回收，需要时用 `Start-Process` 拉起独立进程。

注意 PowerShell 5.1 的一个坑：当环境变量里同时存在 `http_proxy` 与 `HTTP_PROXY`（大小写各一份）时，`Start-Process` 会报「已添加项。字典中的关键字…」。启动前先清理冲突，再补回大写副本：

```powershell
$repo = "D:\notebuddy_main\Notebuddy"
$py = Join-Path $repo "apps\backend\.venv\Scripts\python.exe"
$logs = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$envs = [Environment]::GetEnvironmentVariables()
$http = [string]$envs['HTTP_PROXY']; $https = [string]$envs['HTTPS_PROXY']
foreach ($k in @($envs.Keys | Where-Object { $_ -imatch '^(http|https|all)_proxy$' })) { [Environment]::SetEnvironmentVariable($k, $null) }
foreach ($k in @([Environment]::GetEnvironmentVariables().Keys | Where-Object { $_ -imatch '^(http|https|all)_proxy$' })) { [Environment]::SetEnvironmentVariable($k, $null) }
$env:HTTP_PROXY = $http; $env:HTTPS_PROXY = $https

Start-Process -FilePath $py `
  -ArgumentList '-m','uvicorn','app.main:app','--reload','--host','127.0.0.1','--port','8000' `
  -WorkingDirectory (Join-Path $repo 'apps\backend') `
  -RedirectStandardOutput (Join-Path $logs 'api.log') -RedirectStandardError (Join-Path $logs 'api.err.log') -WindowStyle Hidden

Start-Process -FilePath $py `
  -ArgumentList '-m','app.workers.runner' `
  -WorkingDirectory (Join-Path $repo 'apps\backend') `
  -RedirectStandardOutput (Join-Path $logs 'worker.log') -RedirectStandardError (Join-Path $logs 'worker.err.log') -WindowStyle Hidden

Start-Process -FilePath (Get-Command node).Source `
  -ArgumentList 'node_modules\vite\bin\vite.js','--host','127.0.0.1','--strictPort' `
  -WorkingDirectory (Join-Path $repo 'apps\web') `
  -RedirectStandardOutput (Join-Path $logs 'web.log') -RedirectStandardError (Join-Path $logs 'web.err.log') -WindowStyle Hidden
```

停止这些独立进程：

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'D:\\notebuddy_main\\Notebuddy' -and $_.CommandLine -match 'uvicorn app\.main|app\.workers\.runner|vite'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## 4. 启动后的自检

```powershell
# 后端健康检查，应返回 {"status":"ok","service":"notebook-backend"}
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health

# 前端能否访问后端
Invoke-RestMethod http://127.0.0.1:5173/api/v1/health
```

浏览器打开 `http://127.0.0.1:5173` 后，首页应能加载课程书架与知识树。

## 5. 关于一键脚本 `scripts/dev.ps1`

脚本会先检查数据库迁移，再启动 API、执行器和前端。但在当前机器的 Windows PowerShell 5.1 下存在两个已知限制：

1. **编码**：`dev.ps1` 是 UTF-8 无 BOM，PowerShell 5.1 按 ANSI 解码中文，会报 `ParserError`（`意外的标记`、`字符串缺少终止符`）。解决方式三选一：
   - 用 PowerShell 7 运行：`pwsh -File .\scripts\dev.ps1`；
   - 给 `scripts/dev.ps1` 和 `scripts/restore.ps1` 加 UTF-8 BOM；
   - 直接用上面的三终端方式。
2. **uv 路径**：脚本用 `Get-Command uv` 查找，终端 PATH 未刷新时会直接报“找不到 uv”。

脚本退出时会清理本仓库相关的 node/python 进程，不要在另一个终端同时跑手动启动的服务。

## 6. 日志

手动启动时日志输出到各自终端。用后台方式启动时可重定向到 `data/logs/`：

```powershell
cd D:\notebuddy_main\Notebuddy\apps\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 > D:\notebuddy_main\Notebuddy\data\logs\api.log 2>&1
```

`data/` 已被 Git 忽略，日志不会进仓库。

## 7. 停止

在各自终端按 `Ctrl+C`。如果终端已关闭但进程还在：

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen | Select-Object LocalPort,OwningProcess
Stop-Process -Id <占用进程的 PID> -Force
```

执行器没有监听端口，用任务管理器结束对应的 `python.exe`，或在启动它的终端按 `Ctrl+C`。

## 8. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `端口 8000/5173 已被占用` | 上一次的服务没退干净 | 按上面的方式找到 PID 并结束 |
| 页面能开，但接口全部 500 | 只启动了前端 | 启动后端 API |
| 上传后一直“等待处理” | 没启动执行器 | 启动 `app.workers.runner` |
| `ParserError`、`字符串缺少终止符` | PowerShell 5.1 读取无 BOM 脚本 | 用 PowerShell 7 或三终端方式 |
| `无法将“uv”项识别为...` | uv 不在 PATH | 用 `.venv` 里的 python，或把 `%USERPROFILE%\.local\bin` 加入 PATH |
| 前端 5173 正常但 `/api` 报代理错误 | 后端端口不对 | 确认 API 监听 `127.0.0.1:8000` |
| 解析出的中文全是乱码 | 原 PDF 字体缺 ToUnicode | 换 PPTX/DOCX，或重新导出可复制文字的 PDF |

## 9. 提交前检查

```powershell
cd D:\notebuddy_main\Notebuddy
git status --short
git diff --check
```

确认 `.env`、`data/`、日志和本地测试文件没有进入暂存区。当前分支提交目标为 `feat/agent-dialogue`，不要直接在 `main` 上开发。
