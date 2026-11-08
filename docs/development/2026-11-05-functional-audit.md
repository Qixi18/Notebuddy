# NoteBuddy 功能完整性审计（2026-11-05）

本报告是 `09faff5` 的**修复前快照**；后续分支实现与复测见 [标准处理升级交付记录](2026-11-05-standard-processing-upgrade.md)。本地探针同名 JSON 会被重跑覆盖，升级后的结果另存 `.runtime/audit-20261105/upgrade-probe-results.json`；以下初始实测值保留为审计历史。

## 结论与范围

当前主要功能已有实现，常规资料处理主链能够运行，完整自动回归通过；**仍不能判定各项功能已经完备，尤其不能把标准路线的“解析完成”理解为内容完整**。本轮用合成样本复现了四类内容完整性问题：带少量文字层的扫描正文绕过 OCR、文字页矢量图未进入 DocumentIR、生成快照静默截断、部分双栏正文阅读顺序错误。

代码基线为 `main` 的 `09faff5`（`09faff5 Merge pull request #18 from Qixi18/fix/overall-debug-integration`）。Fetch 成功后，`HEAD...origin/main` 为 `0 / 0`，对共享集成分支为 `1 / 0`。开始时已有 `README.md` 和未跟踪的 `start-notebuddy.bat`，均为前一轮启动入口工作，本轮保留。

本轮审计没有修改产品逻辑、API、数据结构、依赖关系或数据库迁移。新增本报告并更新验收记录；本地探针、合成资料、临时库和输出保存在忽略目录 `.runtime/audit-20261105/`，没有提交、推送或部署。未读取用户密钥、真实课件、会话或业务数据库。

## 功能矩阵

| 功能 | 本轮证据 | 判断与边界 |
| --- | --- | --- |
| 本地准备与启动入口 | `start-notebuddy.bat -Check` 退出 0；官方测试使用项目内 Python/Node | 依赖就绪；没有启动用户正式服务，没有验收全新 Windows 安装 |
| 课程、Notebook、未分类笔记、绑定/移动/删除/恢复 | 课程与 Notebook 生命周期、Workspace、归属和路由相关后端/前端测试随全量回归通过 | 自动覆盖通过；未做真实浏览器逐项操作 |
| 上传、校验、Asset 归属、批次与后台任务 | 上传服务、批次协调、Worker 公平调度、重试/取消及路线测试通过；另有五条实际 HTTP 上传探针通过 | 常规主链可用；PDF 边界内容存在下列缺陷 |
| 标准原生 PDF、本地 OCR、DocumentIR、来源与检索 | 原生 PDF、扫描 PDF、PNG、JPG 及未分类 PNG 的独立 HTTP→Worker 流程通过；包含真实本地 RapidOCR 推理 | 合成简单资料通过，不能推定真实论文、复杂课件和扫描质量通过 |
| 笔记生成、增量写入、幂等、revision/CAS、来源、取消与回滚 | 生成流水线/限额/公式门禁/图片来源/生命周期测试通过；探针正式正文 revision 为 1，来源引用与检索结果非空 | 离线生成闭环通过；真实教学讲解、事实覆盖和真实模型质量未验收 |
| 编辑、草稿、保存冲突、历史恢复、离开保护 | 正文、Workspace、导航、dirty guard 和冲突组件测试通过 | 自动覆盖通过；真实浏览器并发编辑和恢复体验未验收 |
| Notebook/课程问答、证据范围、核验后发布、会话管理 | QA、Agent、课程范围、证据阶段隔离、来源检查及前端助手相关测试通过 | Fake Provider/本地路径通过；没有真实模型、多轮质量或联网来源实测 |
| 知识森林、关系与培养方案导入/撤销 | 森林生命周期、任务、导入与撤销、Web 导航等测试通过 | 自动覆盖通过；上传后自动付费关系分析被现有预算实现关闭，不能承诺每次上传后自动生成藤蔓 |
| 练习、错题、复习产物、术语与反馈 | 对应后端与前端测试随全量回归通过 | 自动覆盖通过；题目教学质量未做真实模型验收 |
| 备份、预览、隔离恢复与旧库迁移 | `test_phase_three_four.py` 的包往返/范围/预览用例，以及隔离迁移测试通过 | 合成隔离数据通过；用户真实库恢复及灾难演练未执行 |
| 设置、视觉预检、处理预算 | 设置、预检、账本/对账/缺失定价拦截等 Fake Provider 用例通过 | 配置假设下的逻辑通过；实际模型连接、额度、价格、供应商账单未检查 |
| Web / Desktop | Web TypeScript/Vite 与 Desktop 主进程 TypeScript 构建通过 | 构建通过；Electron 实际启动、打包分发未验收 |

## 标准路线实际调用链

`Web 上传 API → asset_uploads / uploads / image_assets → Asset + NotebookAsset + 持久上传批次/解析任务 → runner → material_worker / asset_worker → DocumentProcessing → DocumentParseRun + DocumentIR → coordinate_generation_inputs → generation_jobs → notebook_generation_worker → notes/store.write_document → Notebook 正式正文 + 来源映射 + 派生目录/检索`。

PDF 的标准默认解析器是 `native`；可显式选择可选 MinerU。原生 PDF 优先文字层，扫描 PDF 通过本地 OCR 提取，视觉增强依赖额外配置。PPTX/DOCX 标准处理仍经基础 Office 兼容适配器，并带 `office_limited` 警告。标准处理不意味着最终 AI 讲解免费：文字模型生成仍依赖对应模型和预算配置；本轮强制使用 `offline-extractive` 验证写入链路。

## 已复现的问题

### F1 · P1：扫描正文叠加少量页码文字时绕过 OCR

- 触发：整页主体为扫描图片，同时存在可提取的页码 `1`。
- 实测：OCR 被标为可用，但调用次数为 **0**；页面文字只有 `1`，扫描正文的 `MAIN SCANNED CONTENT` 没有提取。质量为 `partial`，`generation_allowed=true`；只有 `figure_not_interpreted` 警告，正文仍可进入自动生成。
- 根因：[pdf_text.py](../../apps/backend/app/document_processing/engines/pdf_text.py) 第 103–104 行将任何文字块视作已有文字层；[adapters/pdf.py](../../apps/backend/app/document_processing/adapters/pdf.py) 第 77 行和第 107 行据此跳过扫描页渲染/OCR；[quality.py](../../apps/backend/app/document_processing/quality.py) 第 232 行允许没有 blocking issue 的 partial 结果生成。
- 影响：带页码、页眉或水印文字的扫描教材可能得到只依据少量文字和图片占位生成的笔记。原始图片仍保留，丢失的是进入生成与文字检索的正文内容。
- 建议：结合文字覆盖率、主图面积和正文密度判断扫描/混合页面；对未解析的主体区域执行 OCR，或阻止自动生成并报告明确原因。

### F2 · P1：文字页的矢量示意图缺失，却报告完整

- 触发：PDF 页面上方有说明文字，正文为矢量圆、连线和箭头，无位图对象。
- 实测：输入有 **5 个绘图对象**；DocumentIR 只有说明文字段落，没有 figure/image 块；质量为 **`complete`**，`issues=[]`，允许生成。
- 根因：[pdf_text.py](../../apps/backend/app/document_processing/engines/pdf_text.py) 第 264 行起读取文本/位图和表格，没有将普通矢量绘图区域转为图像证据；文字页又不走整页扫描渲染。下游质量评估看不到未入 IR 的图形，因而没有完整性警告。
- 影响：电路图、流程图、曲线等以矢量形式保存的 PDF 内容可能未进入笔记生成和结构化来源。原始 PDF 本身未被改动或删除。
- 建议：检测有教学意义的矢量区域，保存可追溯裁图/页面证据；无法解释的图形应进入质量警告，避免误报 complete。

### F3 · P2：标准生成快照静默裁掉长块与表格尾部

- 触发：DocumentIR 含超过 6,000 字符的单块，或较大的结构化表格。
- 实测：**6,128 字符→6,000 字符**；**45×14 表格→40×12**，同时表格文本缩至 6,000 字符。两个末尾唯一标记均消失，输出 `warnings=[]`。
- 根因：[generation/context.py](../../apps/backend/app/generation/context.py) 第 31–34 行和第 126–148 行在标准路线直接切片，未分块保留剩余部分，也未报告截断。此问题在 IR→生成快照边界直接构造合法块复现，未声称使用了真实大表 PDF。
- 影响：原始资料与完整 IR 可以仍在，但进入生成器的内容已不全；后续来源 ID 校验不能补回被删掉的内容。
- 建议：按预算拆分长块与表格并保留共同来源标识；暂不能完整处理时明确标记未覆盖部分，禁止把裁剪结果当作完整输入。

### F4 · P2：部分双栏 PDF 的左右栏正文被合并

- 触发：双栏页面的对象写入顺序为左上、右上、左下、右下。
- 实测：应按列阅读的 `LEFT 1 → LEFT 2 → RIGHT 1 → RIGHT 2` 被读成 `LEFT 1 → RIGHT 1 → LEFT 2 → RIGHT 2`，且每一横行左右两段被合为同一个段落；质量仍为 `complete`，无警告。
- 根因：[pdf_text.py](../../apps/backend/app/document_processing/engines/pdf_text.py) 第 264 行起沿用文字字典的块/行顺序；[adapters/common.py](../../apps/backend/app/document_processing/adapters/common.py) 第 57–85 行连接行文本前没有按栏分区。
- 影响：部分论文与双栏教材的推导、正文和结论顺序错乱，后续生成可能沿用错误上下文。该复现不代表所有双栏 PDF 都会失败。
- 建议：先进行版面分区和栏内排序，再合并段落；增加双栏、跨栏标题、脚注与图注的阅读顺序回归。

本轮没有修复这些问题，也没有将它们纳入现有正式测试集；现有测试全部通过不能覆盖上述反例。

## 验证命令与结果

所有命令从仓库根目录执行。测试强制 `PYTHON_DOTENV_DISABLED=1`、清空外部服务密钥、使用 `offline-extractive`、`native`、`standard` 与本地 RapidOCR；`TEMP`/`TMP` 指向 `.runtime/audit-20261105/temp`。pytest 的 `conftest.py` 另行将 `NOTEBOOK_DATA_DIR` 指向独立测试目录。

| 命令 | 退出码 | 本轮结果 |
| --- | --- | --- |
| `pwsh -NoProfile -File .\scripts\test.ps1 -RealOcr`（最终沙箱外运行） | **0** | Ruff 通过；pytest **580 passed / 1 skipped / 2 warnings**；导航 **52 passed**；Vitest **85 files / 426 passed**；Web/Desktop 主进程构建通过 |
| `.\apps\backend\.venv-document\Scripts\python.exe .runtime/audit-20261105/probe_standard.py` | **0** | 五项探针输出成功，复现 F1–F4；这里的 0 表示探针执行完成，不表示被测行为正确 |
| `.\apps\backend\.venv-document\Scripts\python.exe .runtime/audit-20261105/probe_http_flow.py`（有效扫描 PDF 复测） | **0** | **5/5** 独立 HTTP 上传闭环通过；真实本地 OCR、离线生成、正式正文、来源与检索 |
| `start-notebuddy.bat -Check` | **0** | 依赖检查通过；未开端口、未迁移用户数据库 |
| `.\apps\backend\.venv-document\Scripts\python.exe scripts/check_architecture_boundaries.py --base-ref origin/main` | **0** | 检查通过；该基线无已提交代码差异，不把它当成额外架构完备证明 |
| `git diff --check` | **0** | 差异空白检查通过 |

最终官方测试日志：`.runtime/logs/test-20261105-200105-36476.log`。额外结果：`.runtime/audit-20261105/probe-standard-results.json` 与 `.runtime/audit-20261105/http-flow-results.json`。探针脚本及 JSON 为本机审计产物，未纳入 Git。

五条 HTTP 流程分别为：课程 Notebook 的原生 PDF、扫描 PDF、PNG、JPG，以及未分类 Notebook 的 PNG。每条生成任务完成，正文 revision 为 **1**；原生 PDF 有 **3** 条来源引用，其余每条 **4** 条；每条均命中正文检索并能通过 document API 读取。生成使用离线提取器，不是对真实 AI 讲解质量的验收。

### 失败、跳过与运行限制

- 首次官方回归在沙箱默认临时目录创建 pytest 子目录失败，人工停止，退出 **1**；没有完整测试统计。
- 改为项目内临时目录后，沙箱回归仍在 TestClient 初始化挂起，人工停止，退出 **1**。单独诊断用例加 `faulthandler_timeout=20`，确认 Python 异步事件循环阻塞于本机 `socketpair` 的 `accept`，尚未进入 HTTP 业务；诊断也停止并退出 **1**。随后在沙箱外保留全部数据和模型隔离条件，完整回归退出 **0**。
- 第一版额外 HTTP 探针退出 **1**：复用的手写 PDF 夹具声明图像宽度 1000，而实际 JPEG 宽度为 1200，默认 PyMuPDF 渲染后的 OCR 无可用正文，质量门禁正确阻止生成。更换为由 PyMuPDF 正确封装的合成扫描 PDF 后，五条流程全部通过；没有修改产品解析器。
- pytest 的 **1 项跳过**是可选私人 PPTX 样本缺失。没有读取或补入该私人文件。
- pytest 的 **2 项警告**分别为测试插件重复导入的断言重写警告、Starlette TestClient 使用 httpx 的弃用警告。Web 构建另有 NotebookEditor chunk 约 **693 kB**、超过 500 kB 的性能提示。
- 未执行真实浏览器验收、真实课件质量评估、付费模型/视觉 API、真实网络搜索、供应商账单核对、用户业务库迁移/恢复、全新机器安装或 Electron 实际运行。真实模型的结构化输出、公式/图表理解与知识覆盖仍需独立验收。

## 后续顺序

先修 F1/F2，补齐扫描主体和矢量图的完整性门禁；再修 F3 的无损分块与覆盖记录、F4 的阅读顺序。随后用受控真实样本分别评估原生论文、混合扫描、双栏、公式、表格和图形，最后在明确授权的模型/费用范围内做真实生成与浏览器验收。跨模块/公共契约调整按项目 ADR 流程办理，本报告不代替架构审批。
