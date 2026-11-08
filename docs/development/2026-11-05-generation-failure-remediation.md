# 标准资料生成失败排查与修复（2026-11-05）

## 已确认原因及处理

用户上传的一份标准 PDF 已完成解析，失败发生在笔记生成。通过本机 API 只读取对应任务状态和脱敏设置，未读取 PDF 正文、对话或 SQLite 文件。

首个错误为 `budget_config_missing`：文本模型价格来源缺失。后续确认文本输入/输出单价为 0，价格版本、来源、汇率和日期均为空；预算校验正确在模型调用前阻止生成。

已通过应用设置 API 补齐非密钥配置，不改变密钥、模型、单文件 ¥10 上限或 25% 缓冲。当前官方 `deepseek-flash` 使用已查证的高峰/缓存未命中上界：输入 **USD 0.3 / 百万 Token**、输出 **USD 1.2 / 百万 Token**；价格版本记录为 `deepseek-v4.1-flash-1017-peak-2026-11-05`。2026-11-05 USD/CNY 快照 **6.7156**。来源：[DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing/)、[CFETS 当日汇率表](https://www.chinamoney.com.cn/english/bmkcpr/index.html?tab=2)。来源字段使用不带查询参数的公开入口 URL。保存后重启独立 Worker，API 返回文本预算 ready=true。

用户随后明确授权“允许重试，沿用 ¥10 预算”。只触发一次任务重试，模型调用正常执行；最终被 `math_delimiter_invalid` 门禁拒绝，未追加正文。该次本地预算账本 settled=55 fen、reserved=0、remaining=945 fen。此为按本地保守配置核算的账本金额，不代表供应商最终账单。没有在授权次数以外自动触发下一轮收费重试。

公式兼容修复加载后，用户另行授权“允许再重试一次，沿用剩余预算”。只再触发一次重试（任务 attempt=3）；最终状态 `failed` / `model_failed`，错误为“JSON 修复重试后仍无效：DeepSeek 返回内容不是有效 JSON”。原有的一次格式修复也已用尽；正式正文 revision 仍为 1，上传项为 `generation_failed`。累计账本 settled=127 fen、reserved=0、remaining=873 fen，两个获准重试累计 59 次供应商请求。第二轮未走到完整公式门禁验收，不能据此声称公式问题已获真实验证。此后停止收费重试。

## 代码修复

- `useNotebookGeneration.ts`：批次失败提示显示并去重具体错误原因；把预算配置键名转换为设置面板字段名称，提示先补齐价格/汇率，避免只有失败数量和盲目重试按钮。
- `notebook_generation_worker.py`：补齐一个可本地复现的模型格式兼容缺口：结构化 inlineMath/blockMath 节点中完整配对的 `$…$`、`$$…$$`、`\(…\)`、`\[…\]` 外层包装可确定性移除。公式内部字符、节点 ID 和来源保持不变；原结构/命令/长度/来源/revision 门禁继续运行。缺配对、多段混合或危险命令仍失败。
- 没有修改公式正确性判定规则，没有绕过质量门禁，也未声称已取回或人工审阅这次被丢弃的模型正文；该兼容修复是否解决用户文件的具体触发点，仍需下一次获授权的真实生成验收。
- `ai/deepseek.py`：JSON 解析失败增加固定枚举的错误类别、行列/字符偏移、总长度及白名单内的结束原因。保留 `invalid_json` 错误码、严格解析及请求次数，不修补或猜测模型正文；未知 provider 字段归为 `unknown`，不把正文片段、原始异常数据或任意供应商字段加入提示。该变更提供下一次排查证据，本身不是本次 JSON 失败的根因修复。

已核对实际请求设置：标准生成已传 `response_format={"type":"json_object"}`、`thinking=disabled`、20,000 输出 Token，并有 JSON 格式示例及一次有界修复。与 [DeepSeek JSON 官方要求](https://api-docs.deepseek.com/guides/json_mode/) 对照，不能归因为“未启用 JSON 模式”。现有任务只保存通用错误，未保留解析位置，未读取真实模型正文，故本次具体语法原因仍未知。另确认标准路线一次处理 28 批，后段失败会丢弃未提交的前批结果；LLM 路线已有批次 checkpoint，标准路线尚未复用。本轮没有引入缓存架构或改变正式正文原子提交。

业务/API 字段/数据库 schema/迁移变化：无；生成格式规范化和失败提示行为更新。依赖方向及统一正文写入/CAS 不变。真实设置通过应用接口保存，不将 `.env`、备份、密钥或用户文件纳入 Git。

## 实际验证与限制

- 新增前端三项失败原因回归先 RED（三项失败），修复后与上传相关用例合计 **7 passed，退出 0**。
- Web 全量复测 **428 passed / 1 failed，退出 1**；失败仍为未改动的 `notebook-history-dialog.test.tsx:111` 焦点断言。此次不把它改写成全量通过。日志 `.runtime/logs/generation-error-ui-test-20261105.log`。
- 首次 Web 构建受沙箱 `EPERM realpath src/main.tsx` 阻断，退出 1；沙箱外同一构建 **退出 0**，保留既有 NotebookEditor 大 chunk 提示。日志 `.runtime/logs/generation-error-ui-build-20261105-retry.log`。
- 公式包装的八项参数化回归及真实来源/正文修订闭环先 RED（九项失败），规范化修复后，公式门禁、生成限额 DB 与生成流水线合计 **52 passed，退出 0**；含破损结构/危险命令继续拒绝的检查。使用 Fake Provider 与隔离 SQLite，没有追加付费模型请求。
- 新增八项 JSON 安全诊断用例先 RED（八项失败），补齐诊断后，`pytest tests/test_deepseek_stream.py tests/test_generation_limits.py tests/test_generation_quality_gate.py tests/test_generation_limits_db.py tests/test_generation_pipeline.py -q` **82 passed，退出 0**。使用项目 `.venv-document`、禁用 dotenv/真实密钥、隔离 SQLite；因 Windows 沙箱 socketpair 限制在沙箱外运行，不访问真实模型。覆盖转义/控制字符/缺结束符/尾随内容及未知 provider 字段不泄露。
- 针对修改的 Ruff 与 `git diff --check` 退出 0。未重新声称全量后端已在最终修复上运行。
- 使用本项目启动器 `-Restart` 加载诊断更新后，只读验证 API health=`ok`、Web HTTP 200、本项目 Worker 存在；任务仍为 failed / attempt=3 / model_failed / base revision=1。重启没有触发第四次重试。
- 真实模型验收记录分别为“公式门禁拒绝”和“JSON 自动修复后仍无效”，均未提交正文；任务保持失败，尚未完成用户文件生成验收。不得在这两次一次性授权之外自动重跑。
