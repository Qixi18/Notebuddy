# 消息发送的人设参数校验修复

分支 `feat/overall-inspection`，基线 `822270ea7ad98e8ab08de0a25599f930b33c1378`。开始前检查状态、分支和远端，Fetch origin 后与任务 main 基线为 0 / 0；保留之前所有未提交修改。未提交、推送或合并。

## 原因及文件

前端 `TEACHER_PERSONA.id` 以及普通会话发送 API 已统一为 `vodyanitsa`，后端实际运行的普通消息、流式消息请求模型却仍只接受 `elf` / `doubao` / `feiyu` 并默认 `elf`。用户的请求因此在生成回答之前返回 422。

- `apps/backend/app/schemas/assistant.py`：共用 `TeacherPersonaId` 保持当前值为 `vodyanitsa`；请求边界将三个历史 ID 归一为当前角色，其他未知值仍拒绝。
- `apps/backend/app/schemas/conversations.py`：普通消息和 Agent 流式消息复用上述类型，默认值改为当前角色，不改会话归属、正文写入、证据或生成业务链。
- `apps/backend/tests/test_teacher_persona_contract.py`：20 项回归覆盖三个请求模型的当前值和默认值、历史兼容、未知值拒绝，以及普通/流式 HTTP 请求成功和历史读回。模型生成使用替身，数据库为临时隔离库。
- `docs/api.md`、`docs/backend-data-contract.md`：同步当前人设和兼容规则。检查了前端提交参数及 API 类型，当前发送值已正确，因此未改前端代码。

## 验证

- 新增回归先复现普通及流式请求均 422；修复后与命名、范围、Notebook Agent 相关测试合计 38 项通过。
- 前端相关四文件 25 项通过：会话、流式范围、右侧答疑和课程切换边界。
- 后端 Ruff 全部通过；`git diff --check` 通过。
- 完整后端 `pytest -q`：405 通过、1 失败、4 跳过，退出码 1，不能称为全量通过。日志 `.runtime/logs/teacher-persona-all-backend-tests.log`。
- 失败项：`test_alembic_migration_drill.py::test_upgrade_from_scratch_and_stepwise_downgrade` 第 161 行。单独重跑仍失败。临时库回滚后 `alembic_version` 实际有 `a5e3c8d1f209`、`e29a10c7f501` 两条版本记录，测试 `_version()` 用 `fetchone()` 却断言单条版本为 processing revision。迁移文件及该测试均与 HEAD 相同，迁移环境不导入本次修改的请求 schema。未借本次消息修复改写迁移或回滚规则，建议另行修正多版本断言并完整复核。
- 4 个跳过项：三个显式未开启的真实 RapidOCR 集成用例（PDF、PNG、JPG）及一个可选私人 PPTX 缺失用例。未启用这些材料/模型验收。
- 日志：`.runtime/logs/teacher-persona-red.log`、`teacher-persona-targeted.log`、`teacher-persona-web-tests.log`、`teacher-persona-migration-recheck.log`。

## 本地服务

受控停止旧启动会话 49474 后确认原启动器和端口监听均已退出，沿用此前已获批准、已升级验证的数据目录运行官方 `scripts/dev.ps1`。本次没有新增或修改迁移。新启动会话 14205，日志目录 `data/logs/dev-20261101-131333-18620`。

重启前读取在线 OpenAPI，两个会话请求模型均仍是旧枚举；重启后再次核对，`AssistantRequest`、`ConversationMessageCreate`、`AgentMessageCreate` 的人设值及默认值全部为 `vodyanitsa`，API 健康状态 `ok`，前端 HTTP 200。用户失败输入没有被代发，也没有强制刷新其页面；可直接再次发送。

未读取真实会话内容或密钥，未代发真实消息或调用付费模型，未修改历史会话、真实课件或 `.env`。HTTP 提交与持久化验收仅使用隔离测试库和合成问答。

提交前复核补充：已将隔离迁移测试改为核对完整版本集合，未修改迁移脚本。最终官方完整检查为后端 406 通过 / 4 可选项跳过、前端 456 通过，构建通过，退出码 0；见[最终汇总](2026-11-01-overall-inspection-summary.md)。上方 405 / 1 失败是修复该测试之前的阶段记录。
