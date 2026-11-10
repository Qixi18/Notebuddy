# Notebook-first 答疑验收记录

> 对应路线图：批次 S1 / S3（P0-QA-01、P0-QA-02、P1-QA-11、P1-QA-12）
> 状态：**自动验证已完成；真实模型、真实 PDF/图片、浏览器人工验收未执行**
> 基线：`feat/overall-inspection`，本地工作树（未提交）

> **⚠️ 契约修订（2026-11-06，ADR-0007）**：下文第 1 节描述的"缓冲正文、不发 delta、不外发思维链"口径已被 ADR-0007 部分修订——门禁前正文 delta 与思维链原文恢复实时下发、思维链恢复落库；**但落库内容与核验徽标仍只由证据门禁决定，核验失败仍整段丢弃**，本记录中的安全测试结论（Stage 隔离、AnswerGate、fail-closed）继续有效。历史测试数字只代表其标注基线。

## 1. 历史发布契约（仅适用于上述基线）

以下流程图保留当时的自动测试证据，不描述当前 SSE 时序。现行流式事件和编辑建议以 [API 契约](api.md) 与 [ADR-0007](architecture-decisions/ADR-0007-restore-agent-streaming-and-notebook-edit-suggestions.md) 为准。

```text
提问 + 会话范围（notebook / course / global / 历史 note）
  ↓ 服务端缓冲正文，不发 delta、不外发思维链原文
[Stage 1 Draft]        只输入 Notebook 正文证据（编号 N*）
[Stage 2 Review]       独立输入 初稿 + Notebook(N*) + DocumentIR(D*)，逐条判定
[Stage 2b Web]         按需联网；来源摘要只作弱证据，词面不重合一律降级 uncertain
[Stage 3 Final + Gate] 最终答案逐条主张核对；冲突/无证据 → 停止或标注未核实
[Publish]              持久化 → status → delta（180 字符分段）→ final
```

- Notebook 链路：`app/ai/notebook_qa.py`（原有 A2 流水线，新增物理证据隔离）。
- 课程/全局/历史 note 链路：`app/ai/verified_answer.py`（新增通用门禁）。
- SSE：`app/api/v1/agent.py` 不再转发原始 `delta`/`thinking`；`thinking` 只有一条
  不带正文的 `status: thinking`，且不落库（只保留 `thinking_ms` / `thinking_chars`）。
- JSON 入口：`app/api/v1/conversations.py` 同样过 `verify_answer`。

## 2. 自动测试证据（离线、零付费）

| 用例 | 文件 | 结论 |
|---|---|---|
| Stage-1 绝不含 DocumentIR 哨兵 | `tests/test_notebook_qa_stage_isolation.py` | ✅ 通过 |
| Stage-2 必须能看到 DocumentIR（D 编号） | 同上 | ✅ 通过 |
| AnswerGate 拒绝未被 review 批准的 D 编号 | 同上 | ✅ 通过 |
| D 编号映射到合并 chunks 的正确下标 | 同上 | ✅ 通过 |
| 课程/全局回答只在门禁后发布 delta | `tests/test_course_verified_qa.py` | ✅ 通过 |
| 门禁结构无效 → fail closed，流内无正文 | 同上 | ✅ 通过 |
| 无证据 → `unverified_no_evidence`（不调用模型） | 同上 | ✅ 通过 |
| 模型不可用 → `verification_unavailable` 且不冒称已核实 | 同上 | ✅ 通过 |
| 长笔记尾部章节召回 | `tests/test_notebook_qa_retrieval_recall.py` | ✅ 通过 |
| 正文/资料检索互不串号 | 同上 | ✅ 通过 |
| 候选集 SQL 上界生效 | 同上 | ✅ 通过 |
| `.edu`/`.gov` 后缀不构成"已证实" | `tests/test_web_claim_evidence_quality.py` | ✅ 通过 |
| 摘要与主张无词面重合 → 不支持 | 同上 | ✅ 通过 |
| 提示注入只当数据 | 同上 | ✅ 通过 |
| 历史消息保留核验状态、前端不误报 | `apps/web/tests/assistant-verified-qa.test.tsx` | ✅ 通过 |
| 独立答疑页选定 Notebook 后走 `notebook_id` 会话 | 同上 | ✅ 通过 |

## 3. 尚未验证（需要用户授权/真实环境）

1. **真实模型**：DeepSeek 真实调用下的初稿质量、主张拆分质量、幻觉率。
2. **真实材料**：长 PDF、扫描页 OCR 错字、公式/表格、多 Notebook 课程。
3. **检索基准**：`Recall@k`、来源命中率、查询耗时；当前只有合成材料用例。
4. **浏览器人工验收**：核验状态徽标、SSE 顺序、断线重连、切换 Notebook 不串流。
5. **真实联网**：Tavily 返回质量与"不确定"措辞是否恰当。

> 结论口径：可以说"核验后发布契约与输入隔离已被离线测试证明"；
> **不能**说"回答已真实准确"或"外部来源已被证实"。
