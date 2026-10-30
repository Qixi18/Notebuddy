# 项目内运行环境与生成验收

目标分支：`feat/debug-integration`。

## 交付内容

- `scripts/setup.ps1` 将 uv、Node、Python 与下载缓存放在 `.runtime`，后端使用 `apps/backend/.venv-document`，默认安装锁定的 RapidOCR CPU 依赖及 Web/Desktop 依赖。
- Python 安装不创建全局命令或注册表项，已有 `.env` 不被安装脚本覆盖。运行时、模型、密钥、本地资料和数据库不提交 Git。
- 后端增加显式的 PyMuPDF、fonttools 依赖；RapidOCR 的 ONNX 模型随包保存在虚拟环境内。
- `dev.ps1`、`test.ps1` 优先项目内运行时；检查失败返回非零退出码，开发服务只清理自己启动的进程树。
- 提供独立脚本行为回归及受控生成的 45 页 PPTX 标题、正文和页脚回归。

## 重现命令

```powershell
pwsh -NoProfile -File scripts/setup.ps1
pwsh -NoProfile -File scripts/dev.ps1 -Check
pwsh -NoProfile -File scripts/dev.ps1
pwsh -NoProfile -File scripts/test.ps1 -RealOcr
pwsh -NoProfile -File scripts/tests/local-environment.test.ps1 -NodePath ./.runtime/node/node.exe -PythonPath ./apps/backend/.venv-document/Scripts/python.exe
```

## 已执行的实际功能验证

安装后的本地 OCR 状态为 `ready`。受控 DOCX、PPTX 和扫描 PDF 均完成解析，实际 DeepSeek 生成 6 个笔记小节；课程树出现对应知识点，连续两轮问答成功并保留来源。

随后通过前端 API 封装和当前运行服务，自写约 230 字的学习方法资料并上传 DOCX，首次生成约 8 秒完成，生成 3 个小节、约 609 字，包含 13 条真实资料来源关联。逐项核对了 25 分钟专注、5 分钟短休息、4 轮后的长休息、主动回忆和第 1/3/7/14 天复习计划。此次短文验证未使用 Computer Use，也没有替换现有用户笔记。

先前一次多格式资料生成在 60 秒请求限制处发生 `ReadTimeout`；本机配置备份后将模型超时调至 180 秒，同一任务重试成功。该变更仅保存在本地配置，安装脚本不会改写其他用户的超时或 API 配置。

## 验收边界

私人原课件 `向量与空间_2026.pptx` 缺失，对应测试保留可选跳过；受控 PPTX 回归通过不能代替该原课件的验收。PaddleOCR、MinerU 和外部视觉服务仍为可选路径，本次部署选择原生解析与本地 RapidOCR。

## 提交前整合检查

提交前先同步远端 `e67f00e`。整合测试发现，新增数学质量门禁将模型正文归一化移到异常处理范围外，超长公式会直接抛出异常，无法进入已有的一次格式修复流程。将归一化与首次门禁移回现有校验保护范围，并保留原始节点作为修复输入兜底；修复后的数学门禁、来源校验和原子写入保护保持有效。对应的修复成功、修复失败和数学质量回归共 11 项已通过。

最终整合版本检查：ruff 通过；包含真实 OCR 的完整后端测试 322 项通过、1 项因私人原件缺失跳过；前端 Node 测试 47 项、Vitest 测试 352 项全部通过；Web 生产构建和 Desktop 主进程构建通过。隔离的安装与检查脚本行为回归 4 组通过。Web 构建保留现有的大体积 chunk 提示。
