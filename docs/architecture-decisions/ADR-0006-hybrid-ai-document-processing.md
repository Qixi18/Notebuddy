# ADR-0006：本地优先的 AI 增强资料处理

状态：Proposed。2026-11-08，基于 `09faff5` 和现有功能分支工作区。

用户已在方案讨论后明确要求“开始干”；本 ADR 记录该授权范围，技术审查前不标 Accepted。

## 现状与目标

`llm_reader.read_document` 对所有页面执行视觉读取，成功页面与 LLM 规划/生成已有 ProcessingStep。标准生成没有使用批次检查点；复杂 Tiptap 树直接由模型生成，失败会损失未提交的批次。本项目已有 MinerU 4.x 适配器，但官方启动环境原未安装该 extra。

目标：可靠内容本地提取，困难内容视觉兜底，保留 AI 教学组织与完整证据，减少读图和重复请求。不能以删除原文、公式或降低门禁换取成功。

## 决策与兼容

- 保留公共 `standard` / `llm` 路线；新 LLM 上传快照固定 `reading_mode=hybrid`，可用环境设置回退 `vision`；没有该字段的旧任务继续原视觉路线。
- 新增独立 hybrid reader / local quality 模块：无付费本地 PDF 提取和 RapidOCR 优先；困难页面可由本地 MinerU 进一步结构化；仍可疑或本地解析失败时，以原页视觉读取兜底。无法安全定位区域时优先整页，避免裁掉条件或公式。页码、坐标、来源始终保留。
- 每个成功页用包含文件哈希、解析器版本、模型快照及策略版本的指纹持久缓存；模型输出必须通过既有读页结构验证，unreadable/uncertain 不假装成功。最终仍统一生成 DocumentIR。
- 本地候选必须有版面证据；原始上/下标几何、向量绘图、小图不按普通文字或装饰静默放行，风险直接读取原页。当前优先保真，会对页脚线或小 Logo 等产生保守额外调用，后续只能用经过验收的覆盖证据细化，不能删除警报压低用量。
- MinerU 混合调用显式 local_only：仅 Flash/Basic、禁止适配器远程图像增强、拒绝包内外部 LLM 辅助配置。所有付费视觉调用仅从已有预算/快照/预检 reader 发出。
- 新混合任务使用紧凑、受类型校验的教学草稿，由本地编译成 Tiptap 节点；保留来源、数学和正文质量门禁。旧快照继续兼容现有模型格式。
- 草稿使用已有 Pydantic 与原 DeepSeek 客户端，避免另引入 Instructor 的独立 HTTP/自动重试层而绕过预算。取消检查在每个请求入口运行，包含 JSON 修复、切分和截断重试。
- 标准与 LLM 生成统一复用已验证批次，只有语义输入一致才复用；保持最终正文单次 `write_document` 与 revision/CAS，失败不部分覆盖。
- 所有外部模型请求继续经现有预算、视觉能力预检、取消和持久 Worker；不引入平行正文写入口，不自动额外发起付费验收。

## 依赖与范围

之前：Service → 全页 llm_reader / 标准 parser → DocumentIR → Planner/Composer → Worker → write_document。

之后：Service → 按快照选择 hybrid_reader / 原 reader；hybrid_reader → 本地 parser/MinerU + 原视觉 reader → 同一 DocumentIR；Composer → typed draft compiler → 原质量门禁/批次缓存 → 原 write_document。

不新增数据库表/迁移，不改变已发布迁移、Notebook 权威正文或旧任务路线。MinerU 使用已锁定可选依赖，并通过安装脚本显式保留其 extra；Docling 暂作候选，不同时堆叠解析框架。当前 MinerU 版本许可包含附加条款，按其随包许可使用。

## 验证与回滚

合成 PDF 覆盖可靠文字、扫描/混合页、空白、乱码、公式/表格、局部失败、视觉回退、跨页读序和缓存失效；比较视觉请求次数，不将模拟请求减少冒充真实 Token 下降。验证重试仅执行失败批次、来源与 CAS、预算及取消、旧全视觉任务兼容、typed draft 的编译和失败拒绝。真实成功率、公式保真与费用 A/B 需另行获准测试。

回滚：新上传设 `NOTEBOOK_LLM_READING_MODE=vision`；旧快照与已成功 ParseRun 保留。移除 extra 不影响基础标准路线，但不能把环境缺依赖当成模型能力已验证。
