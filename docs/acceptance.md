# 验收记录与待验收矩阵

## CI 故障复核与本地修复（2026-11-04，未提交）

- GitHub Actions [Run 41789300953](https://github.com/Qixi18/Notebuddy/actions/runs/41789300953) 在 `fix/overall-debug-integration` 提交 `129ed4e3035a8ce5475d4a0ea5f6af3519c2e33a` 上失败：Ruff 通过、后端 pytest **577 passed / 4 skipped / 2 warnings**；Web navigation **51 passed / 1 failed**，因此 Vitest 和后续构建未执行。失败位于 `apps/web/tests/conversation-groups.test.ts` 的 `created_at` 回退时间断言。
- 原测试用本地时区的 `new Date(2026, 9, 20, 10, 0)` 构造输入，却用固定 `+08:00` 时间作为期望；GitHub runner 的 UTC 时区使断言相差 8 小时。本地仅将期望改为同一 `Date` 的 `getTime()`，未修改时间分组生产逻辑。
- 用 Node.js **22.23.4** 显式设置 `TZ=UTC` 复现修订前的 4/5 通过，修订后 Web `npm test` 两次均为 navigation **52/52**、Vitest **426/426**；`TZ=Asia/Shanghai` 下该文件 **5/5**。复核时一次完整 Web 测试曾遇助手坞懒加载等待的偶发超时，已将测试 helper 的等待上限调整为 5 秒，随后两次 UTC 完整复测通过。`git diff --check` 通过。远端 GitHub Actions 复测结果须单独追加，不能从本地结果推定。

## 本地自动验收快照（2026-11-04 13:22，未提交工作区）

- 基线提交 `db2e2dcddf9887394698b5c58f2c88ecf76f6083` 加本轮未提交的 CI/Node/测试夹具修订。Windows、Python 3.12.14、项目内 Node.js 24.20.0。根目录 `pwsh -NoProfile -File .\scripts\test.ps1` **退出码 0**，日志 `.runtime/logs/test-20261104-132257-44988.log`：Ruff 通过，pytest **577 passed / 4 skipped / 2 warnings**，Web navigation **52 passed**，Vitest **85 文件 / 426 测试通过**，Web TypeScript/Vite 与 Desktop 主进程构建通过。Vite 仍有 NotebookEditor chunk >500 KB 警告。
- 用官方 Node.js **22.23.4** 的独立本地二进制复核 Web `npm test`（navigation 52、Vitest 426）、Web `npm run build` 和 Desktop `npm run build:main`，退出码均为 0。`python scripts/check_architecture_boundaries.py --base-ref origin/main`、`git diff --check origin/main` 与工作区 `git diff --check` 均通过。
- 先前 25 项 Vitest 失败来自测试在懒加载坞/编辑器出现前断言，以及旧 `noteDirty` 夹具与现行 `documentDirty` 契约不一致；保留原有行为断言后定向 5 文件 35/35 通过，再经完整回归通过。409 冲突与离开确认得到组件测试覆盖，但仍未做真实浏览器、真实 PDF/图片、外部模型、账单或真实数据库恢复验收。本次没有 GitHub Actions 通过记录。

## 本地失败快照（2026-11-04 12:51，修订前）

- 起始代码基线：`fix/overall-debug-integration` `db2e2dcddf9887394698b5c58f2c88ecf76f6083`；本次 CI/Node/末尾空行修改在未提交工作区。执行环境：Windows、Python 3.12.14、pytest 9.1.1、项目内 Node.js 24.20.0。CI 计划使用 Node.js 22.23.4，尚未通过 GitHub Actions 验证。
- 根目录执行 `pwsh -NoProfile -File .\scripts\test.ps1`，退出码 **1**，日志 `.runtime/logs/test-20261104-125125-36548.log`：Ruff 通过；后端 pytest **577 passed、4 skipped、2 warnings**；Web navigation **52 passed、0 failed**；Vitest **80 files passed、5 failed，401 passed、25 failed**。5 个失败文件为 `agent-dock.test.tsx`（6）、`dock-interaction.test.tsx`（15）、`multi-book-dirty-navigation.test.tsx`（1）、`notebook-document.test.tsx`（2）、`notebook-workspace-save-conflict.test.tsx`（1）。警告为 pytest 插件重复导入及本机缺少 ccache；详细失败名称和分类见仓库外本轮报告。
- 官方脚本在 Vitest 后停止。随后分别执行 Web `npm run build`（TypeScript 与 Vite）及 Desktop `npm run build:main`，退出码均为 **0**；Vite 仍提示 NotebookEditor chunk 大于 500 KB。单独运行架构边界脚本（`--base-ref origin/main`）通过；后端 `test_backend_architecture_boundaries.py` **12 passed**。这些检查均为本地执行，不是 GitHub Actions 通过记录。
- `git diff --check` 与对 `origin/main` 的提交差异检查通过。历史 CI 指出的 5 个文件在当前树中仍有多余末尾空行，本轮仅删除这些空行；未改函数逻辑、断言、数据结构或 API。
- 失败集中在旧助手坞交互和 Notebook 编辑相关 UI 测试。尤其正文离开确认与 409 冲突面板未通过当前测试，尚不能据后端通过推断浏览器中的数据保护行为已验收。未运行真实浏览器、真实 PDF/图片、模型、付费 API 或真实数据库迁移/恢复。

以下失败快照及 2026-11-03、2026-10-30 快照均为历史执行记录，只适用于各自注明的代码基线。当前本地自动验收结果以上方 13:22 快照为准；仍不能据此声称 GitHub Actions 或真实浏览器/资料/模型验收通过。

## 历史快照（2026-11-03）

- 代码基线为 `feat/overall-inspection` HEAD `f52ced9e4cd02772e37621dbf20d0acec789cc3c`；本轮实现和文档修改均留在未提交工作区，没有提交或推送。
- 根目录执行 `pwsh -NoProfile -File .\scripts\test.ps1`，日志为 `.runtime/logs/test-20261103-204501-35044.log`（本地忽略日志）：Ruff 通过；后端 pytest **577 passed、4 skipped、2 warnings**；Web navigation **52/52 passed**。
- Vitest 为 **80 个文件通过、5 个文件失败；404 passed、22 failed**。失败仍集中在 `agent-dock.test.tsx`、`dock-interaction.test.tsx`、`multi-book-dirty-navigation.test.tsx`、`notebook-document.test.tsx`、`notebook-workspace-save-conflict.test.tsx`。干净 `f52ced9` 基线已独立复现同一组 5 文件/22 项失败；本轮未改前端代码，不把这些已有失败归因于本轮后端分层改动。
- 官方脚本在 Vitest 失败后停止。随后分别执行 Web `npm run build` 与 Desktop `npm run build:main`，均通过；Vite 保留 NotebookEditor chunk 超过 500 KB 的既有警告。`git diff --check` 通过。
- API 路径/schema、数据库 schema/迁移和正式正文存储路径未改变。运行时引用审计确认旧 Note API Router 未注册；`api/notes.ts` 与 `useNoteEditor` 没有运行时导入方；旧解析器仍被 Forest 培养方案和 Office DocumentIR 兼容适配器使用。
- 未执行真实浏览器、真实 PDF/图片质量、OCR、外部模型/账单或真实数据库迁移/恢复验收。

## 历史快照（2026-10-30）

- 本轮代码基线：本地 `feat/debug-integration` `0777d0ef6ba6c44d2e498238d605631ee907c6b3`；Fetch 时远端为 `4759ff50c3100894af47dfca72476fe1c14e9e4a`。
- 本轮开始时工作区干净。自动回归：2026-10-30 在仓库根目录执行 `pwsh -NoProfile -File .\scripts\test.ps1`，退出码 1。首阶段 Ruff 发现 15 项错误（`tests/test_agent_skills.py`、`tests/test_quiz.py` 的 import 排序/未使用导入）；脚本在此停止，pytest、Web 测试/构建、Desktop 构建均未运行。详见 `.runtime/logs/test-20261030-231925-46976.log`（本地忽略日志）；本轮未修测试源文件。
- `git diff --check` 通过，修改文档的相对 Markdown 链接检查通过。未执行浏览器、真实材料、OCR、真实模型或真实数据库迁移/恢复。
- 历史报告中的日期、SHA、测试数量只证明当时执行结果，不表示当前 SHA 已重跑。

## 历史自动验证与当前待验收矩阵

| 范围 | 源码/自动验证 | 浏览器/真实资料 | 状态 |
|---|---|---|---|
| Notebook 正文 JSON、revision/CAS、历史快照 | 全量后端 pytest 通过，写入调用及正文所有权已核对 | 并发保存、恢复及未知节点的真实浏览器体验待补 | 自动通过；人工验收待补 |
| 上传、Asset、批次、DocumentIR/ParseRun | 全量后端 pytest 通过，解析器和 DocumentIR 路径已核对 | PDF、JPG、PNG 真实质量和扫描/OCR待评估 | 自动通过；真实材料待验 |
| 生成质量门禁、来源映射、revision 安全 | 全量后端 pytest 通过 | 真实模型、截断、复杂公式/表格/图片质量待评估 | 自动通过；真实模型待验 |
| Agent 范围与证据 | 全量后端 pytest 通过 | 多 Notebook 真实连续问答和来源人工抽查待补 | 自动通过；端到端待验 |
| Forest/Knowledge/Courses 与复杂路由分层 | 架构边界、导入/任务、提案、课程生命周期等用例通过；复杂业务已委派 Service，课程简单列表保留 Router SQL | 完整真实浏览器流程和规模性能待补 | 自动通过；人工验收待补 |
| 旧 Note/Material API、迁移/备份和解析器 | 当前注册路由、运行时调用方、正文写入口与 parser 引用已盘点；兼容迁移和数据保留规则通过代码审查 | 隔离旧库迁移/恢复及外部调用方确认待补 | 静态审计完成；真实数据流程待验 |
| 旧 Note API 客户端 | Note Router 未注册；旧 `api/notes.ts`、`useNoteEditor` 无运行时导入方；旧前端 URL 只重定向到 `/courses` | 当前主流程无需旧 Note API；历史客户端代码仍作为退役代码保留 | 路由/引用核对完成 |

## 可执行验证入口

完整自动回归（需要依赖就绪，可能耗时）：

```powershell
pwsh -NoProfile -File .\scripts\test.ps1
```

官方脚本按源码流程运行后端 Ruff、pytest、Web 测试/构建和 Desktop 主进程构建；附加真实 OCR 项需显式选择。每次记录命令、工作目录、进程退出码、各阶段通过/失败/跳过数及失败证据。不得把 lint/build 通过解释为真实材料、模型或浏览器流程通过。

数据/API 改动还需使用隔离 `NOTEBOOK_DATA_DIR` 覆盖并按相关范围运行后端/前端用例。迁移与备份仅在隔离测试库验证。资料验收须登记材料类型与范围、解析告警、来源位置、正文保护、模型费用/调用及人工抽查结果；不得把私人材料复制进报告。

## 历史证据

下列历史数字和记录留存在版本历史，不是当前 `f52ced9` 工作树的测试结果：2026-10-15 首页知识树专项曾记录其当时的 Web/后端回归及合成 DOCX HTTP 流程；2026-10-30 迁移后隔离浏览器/API交接记录过正文 revision/CAS、森林搜索和 Agent 读取等行为，但明确未运行 pytest/Vitest，也未验收真实资料/模型。相关交接文档已从当前工作树清理，可从 Git 历史追溯；历史数字不可复制为当前 PASS。

## 当前待补的真实验收

1. 真实连续课程资料（PDF 与图片），人工检查解析质量、来源和公式/表格/图像指向。
2. 用户编辑后生成/重试/并发保存保护，确认无静默覆盖、无重复内容。
3. Agent 证据范围、跨 Notebook 隔离、引用支持强度和模型失败路径。
4. 森林在真实 Notebook 下的定位、恢复与性能。
5. 干净目录安装、隔离备份预览/恢复及旧库迁移演练。

任务交付时把新增执行证据追加至顶端快照，并明确未执行项。GitHub 分支保护是否配置必须通过服务端设置核实，本文件不代表已经启用。
