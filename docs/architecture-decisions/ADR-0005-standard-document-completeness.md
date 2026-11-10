# ADR-0005：标准资料处理的完整性与规模升级

- 状态：**Proposed**，待技术审查；不因实现或自动测试通过改为 Accepted。
- 日期：2026-11-05；基线：`09faff5`；工作分支：`feat/improve-standard-document-processing`。
- 授权范围：用户要求参照高星开源项目升级标准资料处理的大小和质量。

## 现状证据

2026-11-05 的历史审计复现过混合扫描页漏 OCR、文字页矢量图丢失、双栏错序、快照裁剪及长 PDF 内存增长；实施和验证摘要见 [验收记录](../acceptance.md)。这些问题是决策基线，不代表当前仍存在；当前行为以源码及后续验收为准。

## 开源调研与选择

2026-11-05 通过 GitHub 官方 API 核对：[Docling](https://github.com/docling-project/docling) 70,140 stars、MIT；[MinerU](https://github.com/opendatalab/MinerU) 83,174 stars（API 未归类许可证）；[Unstructured](https://github.com/Unstructured-IO/unstructured) 15,680 stars、Apache-2.0。星数仅为当日快照，不作为质量证明。

- 借鉴 [Docling 的层次与预算分块、延续表头](https://github.com/docling-project/docling/blob/main/docs/concepts/chunking.md)：保留结构和来源，超长内容分块而非切掉尾部。
- 借鉴 [Docling OCR 流程](https://github.com/docling-project/docling/tree/main/docling/models) 与 MinerU 的版面优先结构化思路：用几何信息区分正文、混合扫描、栏与图形，未解释图形保留证据和警告。
- 对照 [Unstructured chunking](https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/chunking/base.py) 的超长元素拆分与原始元素来源保留：所有生成块继续引用真实持久化 IR 块。

采用现有 PyMuPDF / PDFium / RapidOCR 的轻量 CPU 链及原创适配逻辑。另两种方式是将完整 Docling 作为新必装引擎（新增模型、下载和部署成本），或默认切换可选 MinerU（本机组件和运行契约变化较大）。本轮维持既有安装与付费预算边界，不引入强制模型依赖，不复制上游实现。

## 设计与边界

1. 标准上传默认从 50 MiB / 500 页提高至 **200 MiB / 2,000 页**；已有环境变量及面板配置继续覆盖默认值，图片仍遵守独立限制。接口字段和错误语义不变，capabilities 自动反映有效配置。
2. PDF 按页提取并立即消费 OCR/渲染结果；兼容保留 `extract_pdf` 的收集接口，标准适配器使用页迭代器。每张渲染图在分配前按边长限制分辨率。
3. 使用主图覆盖率、可用文字量和几何位置识别“正文扫描 + 少量页码”；OCR 缺失或失败继续阻止生成。不得以页码代替已读正文。
4. 文字行先按横向几何分组，按栏与跨栏标题排序；无法证明正确的复杂版面不承诺模型级理解。矢量区域转成可引用图片，未解释时保留质量警告。
5. 标准 IR 在持久化前将长文本/表格分为有独立真实 ID 的块，按行拆表并重复表头，保持顺序和全部列；不可安全拆分的超大结构保留并显式失败，不静默删除。生成快照保留完整字段；离线生成也不截掉有效文本。章节上限通过合并溢出章节保留来源，不舍弃尾部块。
6. `Notebook.document_json`、revision/CAS、统一 `write_document`、来源校验、预算、取消/重试/事务、全程 AI 路线不改变。正文现有 1,000,000 字符 / 8 MB / 8,000 节点验证上限仍生效，超限明确拒绝，不声称任意大文档均能生成。

## 依赖、兼容与回滚

依赖方向仍为上传服务 → Document Processing → IR → generation → 统一正文写入。新增的是解析领域内部的版面/分块辅助模块，不引入 API→Worker 的新依赖，不新增正式正文源。无数据库 schema 变更、无迁移。已持久化 ParseRun/生成快照继续可读；重新解析才采用新块与版面版本。旧快照内容已被裁掉的部分只能重新解析/生成恢复，不能凭空补回。

可通过还原本分支代码及显式设置旧上传限制回滚；保留已产生的 ParseRun、原始文件和正文历史，不要求删除或修改用户数据库。

## 验证

先用回归测试复现审计反例，再验证长文本/大表尾标记、超过 400 章节的来源覆盖、两栏加跨栏标题、页码叠加扫描、原生短公式、矢量图与表格边线区分、逐页消费及渲染尺寸。使用隔离库跑上传→解析/OCR→生成→正文/引用/检索，全量 Ruff/pytest/Web/构建；真实资料、真实模型/费用、浏览器人工验收另记，不调用付费 API。
