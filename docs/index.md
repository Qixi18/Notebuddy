# NoteBuddy 文档导航

仓库根目录 [AGENTS.md](../AGENTS.md) 是代码代理的首要规则入口。遇到历史文档与当前代码冲突时，以当前源码及本节“当前权威文档”为准，并把差异补入文档。

## 当前入口

- [项目运行、环境准备与启动](../README.md)
- [协作与 Agent 规则](../CONTRIBUTING.md)、[Agent 简明规则](../AGENTS.md)
- [代码架构](architecture.md)、[模块职责地图](module-map.md)
- [接口](api.md)、[解析](parsing.md)
- [后端调用与业务数据存储契约](backend-data-contract.md)：并行开发共用的调用链、数据归属与本地存储路径
- [架构决策索引](architecture-decisions/README.md)：全局变更公告及待审/已接受决策
- [开发状态、路线图与任务日志](development/README.md)
- [数据迁移](migrations.md)、[运维](operations.md)、[安全](security.md)
- [验收矩阵](acceptance.md)、[答疑验收](acceptance-notebook-qa.md)、[文件预算验收](acceptance-file-budget.md)

## 历史与待审记录

两份旧软件工程概要/详细设计及其配图、两份已完成执行计划已从当前工作树移除，可由 Git 历史追溯。保留的专题交付记录、迁移方案与验收记录只证明各自标注的日期和基线；[ADR 索引](architecture-decisions/README.md)中的 Proposed 仍待技术审查。旧 Note/ParsedPage/知识提案流程须先核对当前路由和数据契约。

查代码时可从 [模块职责地图](module-map.md)定位；Web 路由定义位于 `apps/web/src/App.tsx`，后端 API 注册位于 `apps/backend/app/api/v1/routes.py`。具体调用链和数据边界以架构说明、契约与当前源码为准。
