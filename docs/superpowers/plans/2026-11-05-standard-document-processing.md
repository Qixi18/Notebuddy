# Standard Document Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提高标准文档可处理规模，消除已复现的内容遗漏并保留来源与写入保护。

**Architecture:** 沿用现有上传 → DocumentIR → generation → write_document；只扩展解析内部的页迭代、几何排序、混合 OCR 和无损分块。保留现有来源标识、数据库 schema 和全程 AI 路线。

**Tech Stack:** Python 3.12、PyMuPDF、PDFium、RapidOCR、pytest；现有 React/Vite 验证。

**Spec:** `docs/architecture-decisions/ADR-0005-standard-document-completeness.md`（Proposed）。

## Global Constraints

- 标准默认 200 MiB / 2,000 页；配置覆盖优先，图片独立限制不变。
- 无强制新依赖、外部收费调用、用户数据库操作或已发布迁移修改。
- 保留 Notebook 正文 1,000,000 字符 / 8 MB / 8,000 节点上限和 CAS/来源/预算保护。
- 既有未提交启动文件、README 和审计材料不清理、不混入产品提交。

## Review Focus

- 只有页码/水印的扫描页必须 OCR 或明确阻止生成。
- 矢量表格边线不能重复当作示意图；真实矢量图必须保留图像来源。
- 跨栏标题、短公式和不规则缩进不得被普通双栏规则破坏。
- 超长单元格、超过 400 章节、表格最后一行/列不得被静默删除。
- 大扫描件页图应边生成边消费；旧快照、来源指向与取消/重试仍有效。

## Tasks

### 1. 长内容与章节来源完整性

Files: `document_processing/normalization/blocks.py`, `service.py`, `normalization/sections.py`, `generation/context.py`, `generation/composer.py`, `tests/test_standard_document_upgrade.py`。

- [x] RED：长块/45×14 表格末尾标记在快照和离线输出中存在；401+ 章节全部块被覆盖。
- [x] 实现 `normalize_standard_blocks(document)`：持久化前按字符预算拆段/按行拆表、重复表头、生成不冲突的真实块 ID；重建章节。
- [x] 移除生成快照字段切片，离线输出长文本分段；保留数学/结构验证，不能安全输出时明确报错。
- [x] GREEN：定向 DocumentIR/生成/来源/质量门禁测试。

### 2. 混合扫描、版面与矢量证据

Files: `document_processing/normalization/layout.py`, `engines/pdf_text.py`, `adapters/pdf.py`, `tests/test_standard_document_upgrade.py`。

- [x] RED：页码扫描调用 OCR；无 OCR 时阻止生成；双栏按列排序，跨栏标题顺序正确；矢量图留证据且不报告 complete。
- [x] 按几何分组行/栏，增加主图与文字覆盖判断；矢量区域避开已识别表格并用有界裁图保留证据。
- [x] GREEN：原生文字、OCR、PDFium fallback、表格、图片/矢量来源回归。

### 3. 页迭代与有效规模上限

Files: `engines/pdf_text.py`, `adapters/pdf.py`, `core/config.py`, `.env.example`, `tests/test_standard_document_upgrade.py`。

- [x] RED：标准解析不调用全量页收集接口；大页渲染不先分配超大 pixmap；默认限制与配置覆盖正确。
- [x] 提供 `iter_pdf_pages`，保留 `extract_pdf` 兼容；提高默认限制、更新非敏感示例/文档。
- [x] GREEN：长文合成样本、上传边界与配置测试。

### 4. 集成、审查和交付

- [x] 更新 parsing、API/数据契约、ADR 索引和验收记录，明确大小上限及未验证范围。
- [x] 隔离合成 PDF/PNG/JPG 完整闭环，包含大文本与来源检查。
- [x] `scripts/test.ps1 -RealOcr`、架构边界与 `git diff --check`；记录命令/退出码/跳过项。
- [x] 按 requesting-code-review 技能请求独立审查并处理重要问题。
- [x] 留在指定本地分支供用户检查；不自动推送、合并或部署。
