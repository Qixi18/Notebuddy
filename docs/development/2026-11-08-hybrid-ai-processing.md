# 混合 AI 资料处理交付记录（2026-11-08）

分支：`feat/improve-standard-document-processing`；实现基线 HEAD `09faff5`。本文记录实现验收时的工作区快照；后续提交与集成状态以 Git 及面向 `fix/overall-debug-integration` 的 PR 为准。方案 [ADR-0006](../architecture-decisions/ADR-0006-hybrid-ai-document-processing.md) 保持 Proposed，执行授权来自用户在方案讨论后明确要求“开始干”；提交分支及 PR 已由后续指令授权，技术审查仍需分别完成。

## 行为与改动

- 新上传选“AI 增强”（API 值仍 llm）时，快照固定 hybrid 模式：本地按当前批次原页码提取，可靠文字直接复用；必要时调用已锁定 MinerU 本地 Basic；仍不可靠则用原视觉 reader。无 reading_mode 的历史任务保持原全视觉路径，普通失败重试不会自动采用新策略。
- `document_processing/hybrid.py` 负责质量路由、原始风险保留、视觉兜底和成功页恢复；只对可疑页请求模型。对上/下标、数学字体、原始向量（包括零高度分式线）、小公式图片和缺版面信息的 pypdf 回退采取保守整页视觉。原始风险不被第二份纯文本覆盖，真空白由原页像素确认，局部 uncertain/unreadable 不提升成功。
- `adapters/pdf.py` / `engines/pdf_text.py` 保留上述字体、几何与绘图信号，支持只提取指定页。严格风险规则仅供混合路线使用，标准旧行为保持。`adapters/mineru.py` 支持选页与 local_only，禁用适配器隐藏远程图像增强，并拒绝启用包内外部 LLM 辅助的配置；不允许在本地阶段绕过预算、视觉快照与预检。
- `generation/draft.py` 使用已有 Pydantic 验证紧凑教学草稿，来源短别名本地映射回真实块 ID，程序编译标题、段落/行内公式、独占公式、列表、表格、提示及例题到既有 Tiptap 正文。缺来源、越界来源、危险/破损公式和超限内容拒绝。仅新 hybrid 快照使用，旧模型节点格式兼容。没有新增 Instructor 的独立 HTTP/重试层；原客户端保留统一费用预留与结算。
- `generation/resume.py` / Worker 将标准生成也接到已验证批次缓存，晚批失败不重跑前面的有效批次。标准无效格式不缓存，保留原最终一次格式修复与已有块 ID；LLM 保留受限步数让出。最终仍在完整片段校验后经同一 write_document/revision/CAS 原子写入。
- `ai/request_control.py` 在每次 DeepSeek 非流式请求前检查任务状态；Worker 规划/生成/修复及两种读页器都覆盖内部重试。取消之后不再增加修复请求或预算预留，取消后返回的页结果不缓存。
- 混合本地长段也复用已有无损来源分块，正式持久化前将文本分为不超过 2,000 字符的真实来源块，并重建页章节映射；不裁正文。Office 转换预览沿用原视觉读取和 DOCX 预览页码标签，避免本地原生 Office 结构页码与转换预览混用。
- `setup.ps1 -WithMinerU` 安装锁定 extra；重复 setup 保留已装 MinerU。`dev.ps1` 默认 MINERU_HOME=.runtime/mineru；Notebook 路线与设置说明改为 AI 增强，培养方案全视觉读取文案仍独立。

业务变化：新 LLM 上传默认本地优先、质量回退、紧凑草稿及统一缓存。API 路由/路线枚举变化：无；provider 非敏感快照新增读取策略/本地版本等字段。数据库 schema/迁移变化：无。数据归属、历史版本、软删除、预算共用及统一正文写入不变。依赖前后关系见 ADR；没有增加新的强制框架，启用现有 MinerU 可选依赖。

## 自动验证（实际命令与结果）

Python 均为 `apps/backend/.venv-document/Scripts/python.exe`，Node 使用 `.runtime/node/node.exe`。禁用 dotenv、清空所有真实模型/搜索密钥，使用临时 SQLite 和合成文件。需要 Windows 硬链接/socketpair 的测试在获自动审批后离开沙箱执行，测试数据仍在 .runtime。没有读取用户 PDF、会话或真实库，也没有真实收费请求。

| 检查 | 实际结果与限制 |
|---|---|
| `pwsh -NoProfile -File scripts/test.ps1 -RealOcr` | 退出 1：Ruff 通过，后端 **672 passed / 1 skipped / 1 warning**，导航 **52 passed**；Web **426 passed / 3 failed**，后续构建被脚本跳过。日志 `.runtime/hybrid-20261108/full-check.log` / `.runtime/logs/test-20261108-165731-26892.log`。跳过是可选私人 PPTX；警告是既有 pytest plugin 重复导入。 |
| 首轮 Web 失败 | `agent-dock`、`dock-interaction` 超时及 `notebook-document` 编辑器未就绪。未改超时或放宽测试；编辑器/历史/设置定向 **16 passed**，不能由单独通过推断根因已解决。 |
| `npm test` 原命令复测 | **导航 52 passed，Vitest 86 files / 429 passed，退出 0**。日志 `.runtime/hybrid-20261108/web-retry.log`；保留首轮失败证据。 |
| 最终新增长段兼容处理后定向 pytest | hybrid/draft/limits DB/旧视觉四文件 **67 passed，退出 0**，日志 `.runtime/hybrid-20261108/final-targeted.log`。长段分块先 RED，再验证逐字符拼接无损及真实来源章节覆盖；未将前一轮全量数字写成这一改动后的全量复测。 |
| 提交前重新运行 Ruff 与关键回归 | 混合/草稿/生成 DB/旧视觉/标准升级/600页完整流程六文件 **87 passed，退出 0**；日志 `.runtime/hybrid-20261108/precommit-tests.log`。 |
| Web `npm run build` | **退出 0**，保留既有 NotebookEditor 约 693 KB chunk 提示；日志 `.runtime/hybrid-20261108/web-build.log`。 |
| Desktop `npm run build:main` | **退出 0**；日志 `.runtime/hybrid-20261108/desktop-build.log`。 |
| 脚本解析、stop-dev 选择器、diff | PowerShell setup/dev AST 解析和 `scripts/tests/stop-dev.test.ps1` 通过；`git diff --check` 退出 0。 |
| 架构静态检查 `--base-ref HEAD` | 退出 0；全局单写入/路由边界已检查，但提交差异规则提示无已提交差异，不把它声称为未提交文件的完整差异审查。 |

新增读页/草稿/生成恢复及审查反例均先运行预期失败的测试，再修复。独立 reviewer 使用原始合成 PDF 和真实 Worker + 假 HTTP 验证三类 Important：隐式远程增强、数学证据漏读、取消后继续修复请求。修复后其定向 **35 passed，退出 0**，原始 PDF 反例退出 0，未发现这些已审范围内剩余 Important。最终长段分块复用原模块并由定向回归补验。

## 真实本地解析（不收费）

- 安装命令 `uv sync --locked --extra rapidocr --extra mineru --python <项目Python>` 退出 0，实际 MinerU **4.0.12**，未改变锁文件。
- 合成三页数字 PDF，用 MinerU Flash 仅选第 2 页，原页码 2、两块已知内容保留，退出 0。结果 `.runtime/hybrid-20261108/local-probe-result.json`。
- 合成扫描 PDF 用 Basic 执行真实版面/OCR，已知文本识别成功，推理日志约 2.18 秒，退出 0。首轮探针因缺 Windows multiprocessing 主入口保护失败，修正探针后通过；模型缓存位于 .runtime/mineru。结果 `.runtime/hybrid-20261108/scan-probe-result.json`。
- 扫描探针仍含未解释的原图证据，路由继续要求视觉；不能把“本地 OCR 成功”冒充“此扫描文件零 AI 读取”或“公式已经正确”。
- 三页混合回归中，两页可靠本地来源、一页视觉兜底，**模型读取次数由三页全读变为一页**；这是模拟 Provider 调用次数证据，不是实际 Token、供应商费用或真实材料完成率数据。

## 使用、回滚与待验收

重启本项目后，新上传选择 AI 增强即可使用新快照。已有失败任务保留旧策略；使用现有“切换处理路线”操作会创建新 ParseRun，仍共用原文件预算。新上传回滚设 NOTEBOOK_LLM_READING_MODE=vision，历史来源/正文/缓存不删除。

尚未进行真实用户文件、付费模型 A/B 或浏览器人工验收，未声称原失败 PDF 已生成成功，也不承诺固定节省比例。保守风险识别可能对 Logo、页脚线等多调用 AI；当前只对可靠来源节省读页，质量与可追溯性优先。真实完成率、公式/数字/表格保真及总 Token（包含全部重试）须用同批样本与全视觉基线对比后验收。
