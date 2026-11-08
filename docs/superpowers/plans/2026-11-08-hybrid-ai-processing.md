# 本地优先的 AI 增强处理实现计划

> 执行方式：本会话直接实施，最后独立审查。用户已批准上轮方案并要求开始，不再重复请求方案/执行方式确认。

Spec: `docs/architecture-decisions/ADR-0006-hybrid-ai-document-processing.md`（Proposed）。

目标：降低全 AI 读页与失败重跑消耗，保留完整来源、AI 教学组织和质量/CAS/预算保护。

## 全局约束与文件归属

协调/实施：本会话；技术把关：维护者；交叉审查：最终独立 reviewer。
在用户指定的现有 feature 分支直接增量实施，保留全部既有未提交修改；不创建缺少这些修改的新 worktree、不提交/推送真实数据。
Service 和 Worker 为本会话唯一主编辑者。新模块承担具体职责，不新增空 service。公共路线、数据库 schema/迁移、统一正文写入保持不变。

## Task 1：本地解析候选与质量路由

- 文件：新增 `document_processing/hybrid.py`，扩展 MinerU 适配器按页解析；测试 `test_hybrid_document_processing.py`。
- 接口：`local_pages(path, context, page_numbers=...)` 返回指定原页码候选；`page_needs_vision(page)` 返回明确原因。候选保留原始 PageIR 块/来源，不输出正式正文。
- RED：可靠文字零模型请求，数学缺结构/未知图形/乱码/空页覆盖异常进入回退，真实空白不收费。
- GREEN：原生提取/RapidOCR 只用于可靠内容，MinerU 为困难页的可选本地增强；缓存带策略和实际解析器版本。
- 验证：定向 pytest；安装锁定 MinerU，使用合成资料做本地实测，记录不可用/下载限制。

## Task 2：混合读页持久恢复与快照接入

- 文件：`hybrid.py`、`llm_reader.py`、`config.py`、`core/config.py`、`service.py`。
- 接口：`read_hybrid_document(db, run, asset, path, progress, max_new_pages)` 与原 reader 同一返回契约；快照 `reading_mode` 固定新策略，旧快照不改变。
- RED：只对可疑页发视觉请求、晚页失败后复用成功页、快照改变缓存失效、budget/取消继续阻止请求、不提升不完整 IR。
- GREEN：视觉调用复用原 `read_page_image` 及预算作用域，整页安全兜底；将本地和视觉页统一为来源可追踪的 DocumentIR。
- 验证：混合、旧视觉、质量、预算相关测试。

## Task 3：紧凑教学草稿与来源保真编译

- 文件：新增 `generation/draft.py`，修改 `composer.py`，新增 `test_generation_draft.py`。
- 接口：Pydantic 草稿 schema + `compile_draft(result, allowed_sources)` 返回 Composition；仅新混合快照启用，旧 Tiptap 输出保持兼容。
- RED：标题/混合文字公式/列表/表格/警告编译，缺来源/越界来源/危险公式/超限拒绝；实际假 HTTP 往返可运行。
- GREEN：提示词只要求小型教学 schema，来源用批次短别名且本地映射真实 ID；保留完整有效输入，格式修复有界且经过预算。
- 验证：新草稿、生成限额、公式/来源门禁回归。

## Task 4：统一生成检查点与失败批次恢复

- 文件：`generation/resume.py`、`workers/notebook_generation_worker.py`；扩展生成测试。
- RED：标准路线后批失败只重跑失败批；缓存只保存通过结构/来源校验的批次；revision/来源变化不可误用；最终写入仍原子。
- GREEN：统一原 compose_batch 路径，指纹增加编译/提示版本，保留旧任务语义；LLM 受限步数后让出，标准保留逐批检查并在每次模型请求前再检查取消。
- 验证：标准/LLM Worker、重试/CAS/预算、原子写入测试。

## Task 5：安装、界面语义、文档与交付

- 文件：`scripts/setup.ps1` 显式 extra、设置/路线选择的说明文字、`.env.example`、README、parsing、架构/API/数据契约及验收记录。
- 验证：相关 Web 测试和构建、后端 Ruff/pytest、架构边界、脚本解析、diff check；独立整体审查并修复重要发现。
- 记录真实本地解析/模拟模型/真实付费模型各自结果，不承诺未经测量的节省比例或真实成功率。

## Review Focus

- 解析“有文字”却漏公式/扫描主体时误放行。
- 真实空白与解析失败混淆，或裁剪造成数学上下文丢失。
- 缓存指纹缺引擎/模型/提示版本，重试来源/页码变动。
- 草稿短来源 ID 映射不完整或编译损坏公式。
- 部分失败引发正文部分写入，或模型重试绕过预算/取消。

## 进度

- [x] Task 1
- [x] Task 2
- [x] Task 3
- [x] Task 4
- [x] Task 5

执行证据与实际限制：`docs/development/2026-11-08-hybrid-ai-processing.md`。最终真实付费模型、用户文件及 Token A/B 未执行，不作为本地验证已通过项目。
