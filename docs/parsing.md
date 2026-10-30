# 资料解析与 DocumentIR

本文描述当前 Document Processing 主路径。旧阶段文档中的 `ParsedDocument → ParsedPage → ParsedBlock` 是早期解析模型/兼容实现的历史描述，不是当前 Notebook 正文，也不能作为新解析链的默认契约。源码入口优先从 `apps/backend/app/document_processing/`、`app/api/v1/materials.py`、Asset/ParseRun 模型及 `app/workers/` 核对。

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
