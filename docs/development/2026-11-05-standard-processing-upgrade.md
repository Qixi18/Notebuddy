# 标准资料处理升级交付记录（2026-11-05）

## 结果

工作分支：`feat/improve-standard-document-processing`，由 `main` 的 `09faff5` 创建。实现留在本地未提交工作区，未推送、合并或部署。前一轮启动文件、README 启动说明和修复前审计记录均保留。

目标是提高标准资料可处理规模和内容完整性。默认文档上限从 **50 MiB / 500 页** 提高至 **200 MiB / 2,000 页**，已有配置仍覆盖默认值；图片独立限制不变。实际新增 **600 页**合成 PDF 完整流程验证，检查每页标记、最终正文和全部真实来源行。

参考项目、当日星数、取舍和回滚方案见 [ADR-0005](../architecture-decisions/ADR-0005-standard-document-completeness.md)（Proposed）。本轮借鉴 Docling、MinerU、Unstructured 的结构、几何/OCR 与无损分块原则，使用现有 PyMuPDF/PDFium/RapidOCR 实现，不复制上游代码，不新增强制模型依赖。

## 文件与行为变化

| 文件/模块 | 修改目的与行为 |
| --- | --- |
| `core/config.py`、`.env.example`、`SettingsPanel.tsx` | 更新文档默认大小/页数及面板占位提示；配置覆盖和现有字段保持兼容 |
| `document_processing/engines/pdf_text.py` | 增加页迭代接口，保留原收集接口兼容；避免文字布局字典携带图片二进制；按联合图像覆盖和正文位置判断混合扫描；分配前限制渲染尺寸，拒绝异常几何 |
| `normalization/layout.py`、`adapters/pdf.py` | 分离跨栏行、按正文栏与跨栏锚点排序；文字页矢量图保留可引用裁图并带未解释警告；已识别表格边线不重复转图 |
| `normalization/blocks.py`、`service.py` | 标准解析持久化前按最多 2,000 字符拆长文本、按行拆表并重复表头，给每片生成真实、不冲突的块 ID；保留页码、bbox 和来源，再重建章节 |
| `ir.py`、`normalization/sections.py` | 大单元格不再在序列化时切为 2,000 字符；超过 400 章节时合并尾部来源，导航规模有界且块不丢失 |
| `generation/context.py`、`composer.py` | 快照保留完整文字、表格和图形字段；离线长段落分段输出，数学超限走既有显式验证，避免静默切掉内容 |
| `tests/test_standard_document_upgrade.py` | 新增 19 项来源、版面、OCR、章节、序列化、规模、逐页消费和渲染边界回归 |
| `tests/test_standard_large_source_pipeline.py` | 新增 600 页 HTTP 上传→解析→生成→正文/来源端到端用例 |
| README、parsing、API/数据契约、ADR 索引与计划 | 记录有效上限、兼容边界、开源依据、执行步骤及验证证据 |

业务变化为标准解析与来源完整性改进及默认接收上限提高。**API 路由/字段变化：无；数据库 schema/迁移：无；新增必装依赖：无。** 原有 generation → DocumentIR、统一正文 `write_document`、revision/CAS、历史、取消/重试、幂等、预算和来源校验均保留；没有新的正文源或 API→Worker 反向调用。

## 本轮验证

测试均使用项目 Python/Node、隔离临时目录和合成资料。强制 `PYTHON_DOTENV_DISABLED=1`、外部服务密钥清空、离线生成、标准 native 解析；真实 OCR 项使用本机 RapidOCR。没有读取真实课件、密钥或业务库，没有调用真实付费模型。

| 实际命令 | 退出码与结果 |
| --- | --- |
| `python -m pytest apps/backend/tests/test_standard_document_upgrade.py -q --tb=short`（项目 Python） | 最终 **0，19 passed**；初始 10 项按预期 RED，新增默认限制/单元格和审查反例也分别先失败再修复 |
| `python -m pytest apps/backend/tests/test_standard_large_source_pipeline.py -q --tb=short` | **0，1 passed**；600 页每页标记、正文 revision=1 和引用来源行全集相符 |
| 标准升级 + 生成限额/流水线 + Document Service + IR e2e 定向 pytest | **0，67 passed / 1 warning**（审查补充前的中间检查） |
| `pwsh -NoProfile -File .\scripts\test.ps1 -RealOcr`（审查补充前） | **0**；后端 **596 passed / 1 skipped / 2 warnings**，导航 52、Vitest 426、Web/Desktop 构建通过；日志 `test-20261105-203434-13956.log` |
| 同一官方命令（最终代码） | **1**；Ruff 通过，后端 **600 passed / 1 skipped / 2 warnings**，导航 52；Vitest 425 通过、1 失败，脚本按设计停止。日志 `.runtime/logs/test-20261105-204209-26416.log` |
| `node node_modules/vitest/vitest.mjs run tests/notebook-history-dialog.test.tsx`（Web 目录） | **0，7 passed**；诊断上述焦点断言失败，未修改该测试或产品弹窗 |
| 项目 Node/npm 的 `npm test`（Web 目录，最终复测） | **0**；导航 **52 passed**，Vitest **85 files / 426 passed** |
| 项目 Node/npm 的 `npm run build`（Web） | **0**；TypeScript/Vite 通过 |
| 项目 Node/npm 的 `npm --prefix apps/desktop run build:main` | **0**；Desktop 主进程构建通过 |
| 项目 Python 的 `python -m ruff check apps/backend/app apps/backend/tests/test_standard_document_upgrade.py apps/backend/tests/test_standard_large_source_pipeline.py` | **0** |
| `python scripts/check_architecture_boundaries.py` | **0**；全源码规则通过，未指定基线的 changed-file-only 规则不执行；另运行 `--base-ref origin/main` 返回 0，但未提交差异不由该脚本的提交差异检查覆盖 |
| `.runtime/audit-20261105/probe_standard.py` 及结果断言 | **0**；原审计样本现在 OCR=1、矢量图质量 partial 且保留 figure、双栏顺序正确、表格/长段尾部标记存在 |
| `.runtime/audit-20261105/probe_http_flow.py` | **0，5/5**；原生 PDF、扫描 PDF、PNG、JPG、未分类 PNG 均写入正文，来源与检索非空 |
| `git diff --check` 与文档链接/空白检查 | **0** |

Web 单文件/全量复测及构建日志为 `.runtime/logs/standard-upgrade-web-20261105.log`。最终数据已通过全部后端用例和后续完整 Web 复测，但不把最后一次官方脚本的退出码 1 改写成 0。

最终官方脚本中的唯一 Web 失败是未改动的历史版本弹窗恢复后焦点断言（`notebook-history-dialog.test.tsx:111`，课程分支）；单文件 7 项及完整 Web 426 项复测均通过。记录为未稳定复现的时序风险，不宣称已修复其根因。跳过项为缺失的可选私人 PPTX；两项后端警告为测试插件重复导入和 Starlette/httpx 弃用。Web 构建仍有 NotebookEditor 约 693 kB 的 chunk 提示。

## 独立审查

只读审查复现了分片扫描未 OCR、短跨栏标题连接两栏、最低 1 DPI 对异常大页仍分配超大图三项问题；都补充回归并修复。随后独立运行五项合成探针，验证短标题、OCR 开/关、重叠图片面积去重和超大页分配前拒绝，退出 0；限定复核范围内没有剩余重要问题。独立审查没有替代全量测试或真实材料验收。

## 使用限制与后续风险

- 新默认不覆盖已有的 50 MiB/500 页等显式配置；需要更高上限时调整对应设置/环境变量。
- 逐页释放原始页面图片不等于整条链为常数内存：IR、生成快照和最终正文仍随文本/块数增长。600 页用例不是 200 MiB 文件的内存峰值或真实速度基准。
- 正文原有 **1,000,000 字符 / 8 MB / 8,000 节点**、数学和模型请求/费用门禁仍生效；超限时显式拒绝，不能承诺任意大文档最终生成。
- 旧 ParseRun/快照/正文不自动重写。之前已经被裁掉的来源内容需要重新解析和显式生成；用户编辑与历史保留。
- 复杂多栏、图形语义、公式和表格教学质量仍需真实资料及真实模型评估。本轮没有真实浏览器、真实模型/账单、用户库迁移/恢复或 Electron 实际运行验收。
