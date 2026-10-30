# 资料解析与 DocumentIR

本文描述当前 Document Processing 主路径。旧阶段文档中的 `ParsedDocument → ParsedPage → ParsedBlock` 是早期解析模型/兼容实现的历史描述，不是当前 Notebook 正文，也不能作为新解析链的默认契约。源码入口优先从 `apps/backend/app/document_processing/`、`app/api/v1/materials.py`、Asset/ParseRun 模型及 `app/workers/` 核对。
## 两条处理路线

设置面板的“默认文档处理路线”可在**标准处理**和**全程 AI**之间切换，保存后影响新上传；上传入口可单次覆盖。已登记的资料和重试任务保留当时的路线和模型连接身份。

标准处理继续使用下面的本地解析/OCR流程。全程 AI 仅在本地验证文件并转成页面图片，之后通过当前主模型 API 完成页面读取、笔记章节规划、正文生成与跨课程关系判断；不调用本地文字/OCR/MinerU提取语义，也不静默降级为离线笔记。

- PDF 使用已有 pypdfium2 逐页渲染；PNG/JPG 作为一页输入。PPTX/DOCX 先转 PDF，支持本机 Windows Office、`NOTEBOOK_SOFFICE_PATH` 指定的 LibreOffice，以及显式配置 `NOTEBOOK_GOTENBERG_URL` 的自托管 Gotenberg。
- Office 转换在隐藏子进程中进行。若 COM 复用了用户已有的 Office 进程，拒绝操作该实例；可关闭对应应用后重试，或改用 LibreOffice/Gotenberg。转页失败与超时保留原始文件。DOCX 的页码只称“转换预览第 N 页”。
- 全程 AI 默认允许 200 MiB、2,000 页，分别由 `NOTEBOOK_LLM_MAX_UPLOAD_MB`、`NOTEBOOK_LLM_MAX_PAGES` 控制；标准处理仍使用原大小/页数限制。原始图片保留现有 20 MiB 上限。
- 页面成功结果、规划调用和正文批次保存在 SQLite `processing_steps`；相同身份的成功步骤可复用。读取每轮最多处理两个新页面，然后让出执行器；已保存的页面图片不重复渲染。正文和藤蔓处理也在批次之间轮转，Notebook 内按原顺序串行写入。
- 任一不可读页面会阻止整份资料作为成功来源；模型明确判为空白的页单独记录。模型生成的 ID、层级及来源映射由服务端校验。笔记写入和藤蔓分析分别报告状态，藤蔓失败可独立重试。
- AI 页面读取容忍额外元数据，`level`、`text`、`uncertain` 留空时使用未指定层级、空文本和未标记不确定的默认值；公式、表格等实际内容仍保留。空内容、不可读页和非法层级仍报错，格式细节不再单独阻断整个文件。
- AI 章节规划允许模型给出更深的正整数层级及额外元数据；深层小节映射到编辑器支持的第三级，标题、原文块和页码继续保留。来源覆盖与来源身份仍必须有效。
- AI 结构化调用最多尝试三次。暂时空白响应和临时网络错误可重试；输出明确截断时逐次扩展预算，自动扩展上限为 32,000 token。章节规划首轮预算为 16,000 token，为模型思考和最终结果留出空间。持续失败仍报告错误，认证或余额错误不自动重试；截断结果不作为成功检查点。
- 失败资料可“改用全程 AI”，不需要重新上传原件。旧成功读取版本保留；同一上传批次中改换路线的文件会分别创建生成任务。已成功生成的正文不会因为切换设置或重新读取而自动重复追加。

全程 AI 需要当前模型支持图片内容；已用 DeepSeek 官方 `deepseek-flash` 做过合成资料端到端验证。模型识别与语义覆盖仍需针对实际课件核对。复杂图表、模糊扫描、异常超长单块或模型截断会明确报错，不把未处理内容当作完成。失败请求可能已被服务商计费；检查点只能减少可避免的重复调用。

## 标准处理

标准路线保留兼容的 Parsed* 解析器；新 Notebook 正文仍以版本化 DocumentIR 与受控生成写入为准。

## 当前职责

- **原始 Asset**：稳定标识和文件元数据，按 Notebook 所有权/使用关系登记；原文件保存在配置数据根目录。
- **DocumentParseRun**：一个 Asset 的解析尝试/版本，标记是否当前、状态、版本和质量信息；失败或重新解析不应把旧证据误认为新版本。
- **DocumentIR**：该 ParseRun 的结构化解析结果，含块、来源位置、提取方式及质量问题；它是来源资料的解析产物，不是 Notebook 正文。
- **Notebook.document_json**：通过生成质量门禁后写入的用户可编辑正文，是唯一正式正文来源。

`DocumentPage` 等历史逐页表或 Parsed* 类型如仍由兼容 API/迁移使用，应按具体调用标注兼容边界；不能仅凭命名移除。新流程关联路径应从 Asset 到 ParseRun，再到其 DocumentIR 与来源位置核对。

## 上传、重试和生成

上传端点验证允许的文件名/容器/大小，登记 Asset 与 Notebook 资源归属，并建立持久任务/上传批次状态。批次关闭后协调器按每个 Asset 的幂等记录推进解析与生成。缺少 Worker 时任务不会在请求进程内完成。

生成前由当前 ParseRun 的质量结果决定是否可用，并保留来源映射。生成任务固定输入和基准正文 revision；Worker 对模型结果做结构及内容校验，再合并写入 `Notebook.document_json`。任务失败、被拒绝或遇到 revision 冲突不能部分覆盖用户正文。实际事务和边界以 `notebook_generation_worker.py`、`generation/context.py`、`notes/store.py` 及测试为准；真实 PDF/图片、OCR 质量仍需单独验收。

## 图片、扫描件和格式

当前主验收重点为 PDF、JPG、PNG；现存能力可能仍接受 PPTX、DOCX 等兼容格式。生效白名单与上限应查看 `GET /api/v1/config/capabilities`、上传校验和 OCR 配置，不能从旧文档推断。图片可作为 Notebook 资源进入图片解析/DocumentIR 流程；Notebook 正文图片附件另有 attachment 路径，二者用途不同。

扫描 PDF 的 OCR 是否执行取决于配置、引擎和资源限制。没有有效文字层或 OCR 证据时必须保留告警/质量状态，不生成伪造的来源。公式、表格、版面、图像含义及来源指向的质量均需要真实材料人工抽查。

## 历史接口与验证状态

`materials` 路由仍注册旧课程资料/页面类接口，作为兼容能力保留；是否下线需检查前端、外部调用方、迁移及历史记录，不能仅因 Notebook 主链存在就删除。Notebook 生成、DocumentIR 与兼容 API 的当前路由见 [API 契约](api.md)。当前已核对代码路径，但本文不宣称本轮运行过自动测试或真实材料验收；见 [验收矩阵](acceptance.md)。
