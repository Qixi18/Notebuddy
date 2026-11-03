# DEV-001：工程治理与架构规范化（阶段一至四及服务边界增量）

## 任务与基线

- 日期：2026-11-03
- 需求/背景：建立统一协作规范、模块职责地图、自动化门禁和可持续的交接记录。
- 验收目标：阶段一至四的仓库内制度与配置落地；增量抽取若干垂直服务用例且保持 HTTP 契约；真实 CI 运行和 GitHub 保护状态分别记录，不以本地文件推定远端状态。
- 修改等级：L2；新增服务分层代码但不修改业务 API、数据库结构或 Notebook/DocumentIR 数据契约。
- 起始分支与 SHA：`feat/overall-inspection` @ `740c6f3`。开始前已有阶段一/二未提交文档改动。
- 任务协调人：待项目参与者填写。
- 共同开发者：待项目参与者填写。
- 交叉审查者：待项目参与者填写；当前未记录独立协作者复审。
- 技术把关者：项目维护者（用户）。
- ADR：关联 ADR-0001/ADR-0002 均保持 Proposed；本任务没有改变其架构状态。

## 方案与实现

- `.github/workflows/ci.yml`：在 Windows runner 安装 Python 3.12、Node 22、锁定的 uv 及 Web/Desktop/Backend 依赖；运行架构检查、差异空白检查和既有 `scripts/test.ps1`。
- `CONTRIBUTING.md` 增补三人并行切片协议，明确负责人/文件归属、接口先行、集成顺序、共享文件唯一主编辑者及交接状态核对；PR 模板和任务日志模板增加切片、依赖与集成负责人字段。
- `.github/pull_request_template.md`：要求填写任务角色、L1/L2/L3、工作切片/文件归属、接口依赖/集成负责人、API/数据影响、各类验证结果和风险。
- `scripts/check_architecture_boundaries.py`：标准库静态检查，扫描 API 路由是否绕过 Service 直接调用 `write_document`；确认 `notes/store.py` 唯一底层 writer 定义；对 PR/push 相对基线新增/修改的 Service 检查 FastAPI 依赖、兼容聚合入口检查新注册端点、页面检查直接 `fetch`。现有 rules/relations/suggestions 子路由也会在下一批按具体迁移逐步移除 HTTP 错误映射。
- `docs/development/`：增加目录规则、状态、路线图、日志模板和本任务记录。
- 更新 README、文档索引及 `docs/operations.md`，描述 CI 状态检查名与远端保护的配置边界。
- 后续服务边界增量：`notebook_document.py`、`notebook_order.py`、`notebook_reading_position.py`、`notebook_relations.py` 与 `notebook_suggestions.py` 使用框架无关的 `ApplicationError`；关系列表和建议列表的查询/响应装配下沉到 Service。新增 `services/document_reads.py` 承接解析结果读取、DocumentIR/证据/覆盖率组装、资源归属校验及渲染/图片路径解析；`material_routes/documents.py` 保留 HTTP 参数、response_model 和 FileResponse，processing 路由改为依赖共享应用服务而非另一个路由模块。`quiz.py` 暂保留 FastAPI 异常契约，因当前全局架构扫描显示它仍依赖 FastAPI。
- 兼容聚合入口仍保留 `_document_payload`、`get_asset_document`、`get_document_coverage` 等导出。未修改数据库 schema、公共 API 路径/字段或 DocumentIR 契约；未调用真实资料、模型或付费 API。

## 验证

| 检查 | 命令或环境 | 结果 | 限制 |
| --- | --- | --- | --- |
| 修改前基线盘点 | PowerShell 查看工作区、CI、脚本、Hook、包锁文件 | 完成 | GitHub branch protection 未从管理员界面核实 |
| 架构规则设计核对 | 对照当前 `api/v1`、`services`、Web `pages` 的源码引用 | 完成 | 未执行新 checker；静态规则尚无运行证据 |
| 文档链接核查 | PowerShell 相对 Markdown 链接路径检查 | 已执行，未发现缺失目标 | 不是 Markdown 渲染/拼写检查 |
| 差异空白检查 | `git diff --check` | 退出码 0 | 新增未跟踪文件的内容不包含在 Git diff 检查范围内 |
| 分层增量静态复核 | 调用点、兼容 re-export、Service FastAPI import 扫描 | 新增/本次改动的 Service 未引入 FastAPI；关系列表查询采用原有方向及排序语义 | 全仓仍有历史 `quiz.py` FastAPI import；未运行 architecture checker 或产品测试，静态复核不能证明运行时行为 |
| 完整 CI/产品测试 | `scripts/test.ps1` / GitHub Actions | 未运行 | 等待 workflow 首次运行；不记录为通过 |
| 浏览器/真实材料/模型验收 | 未执行 | 未运行 | 不属于本次仓库治理文档与配置验收 |

## 结果与交接

- 完成状态与未确认事项见 [当前状态](../../current-status.md) 和 [路线图](../../roadmap.md)。阶段三/四仓库内配置和部分后端分层已实施；后端边界收敛与业务回归仍未完成。
- 远端 `main` / `feat/debug-integration` 的规则集、Required status checks、审查人数、禁止强推/删除尚未通过管理员核实或修改；推荐检查名称为 `CI / quality`，需先待 GitHub 实际运行确认。
- 当前工作区未提交；结束 SHA/PR：未提交 / 无 PR。
- 后续由维护者观察 CI 首次运行并配置远端保护；后续业务开发按本目录模板记录开发日志。
