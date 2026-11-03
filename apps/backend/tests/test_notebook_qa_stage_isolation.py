"""P0-QA-01：Stage-1 初稿请求必须与 DocumentIR 物理隔离。

路线图要求：在 DocumentIR 里埋一个只会出现在原始资料里的哨兵字符串，然后拦截
Fake Provider 实收的 messages，逐字段断言该哨兵绝不出现在 Stage-1（初稿）请求中；
Stage-2（主张核验）请求则必须能看到它。只检查最终答案不含哨兵是不够的。
"""

from __future__ import annotations

import json

from app.ai import notebook_qa
from app.notes.document import normalize_document
from app.notes.store import write_document
from tests.notebook_fixtures import make_asset, make_notebook, persist_ir

pytest_plugins = ["tests.notebook_fixtures"]

SENTINEL = "DOC_IR_ONLY_SENTINEL"


class RecordingClient:
    """按调用顺序返回固定 JSON，并记录每次调用实收的 messages。"""

    configured = True
    last_usage = None

    def __init__(self, responses: list[dict], *, configured: bool = True) -> None:
        self.responses = responses
        self.calls: list[list[dict]] = []
        self.configured = configured

    def complete_json(self, messages, **_kwargs):
        self.calls.append(messages)
        index = len(self.calls) - 1
        assert index < len(self.responses), f"unexpected provider call #{index + 1}"
        return self.responses[index]

    # 便于测试断言：把所有 message 正文拼成一个大字符串
    def transcript(self, index: int) -> str:
        return json.dumps(self.calls[index], ensure_ascii=False)


def _flatten(messages) -> str:
    return json.dumps(messages, ensure_ascii=False)


def _stage_evidence_ids(messages, marker: str) -> list[str]:
    """从请求正文里取出模型实际看到的证据编号（按标记切出 JSON 段落）。"""

    tail = messages[-1]["content"].split(marker)[-1]
    return [item.get("id") for item in json.loads(tail)]


def _notebook_with_body(db, text: str = "极限描述函数在一点附近的变化趋势。"):
    book = make_notebook(db, None, "未分类笔记")
    write_document(db, book, normalize_document({
        "type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1, "blockId": "h-1"},
             "content": [{"type": "text", "text": "极限"}]},
            {"type": "paragraph", "attrs": {"blockId": "p-1"},
             "content": [{"type": "text", "text": text}]},
        ],
    }), expected_revision=0, origin="autosave")
    db.commit()
    return book


def _document_with_sentinel(db, book, *, query: str = "极限"):
    asset = make_asset(db, book, "教材.pdf")
    persist_ir(db, book, asset, sections=[(
        "第一章 极限",
        [f"{query}的定义见原始资料。{SENTINEL} 当 x 趋近于 a 时 f(x) 趋近于 L。" * 3],
    )])
    return asset


def _happy_path_responses() -> list[dict]:
    return [
        {"answer_markdown": "初稿：极限描述函数附近的变化趋势。"},
        {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                     "evidence_ids": ["N0"], "needs_web": False}]},
        {"uncovered_claims": []},
        {"answer_markdown": "最终答案：极限描述函数附近的变化趋势。"},
        {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                     "review_claim_ids": ["claim-1"], "evidence_ids": ["N0"], "source_ids": []}]},
        {"uncovered_claims": []},
    ]


def test_stage1_draft_never_receives_document_ir(session, monkeypatch):
    book = _notebook_with_body(session)
    _document_with_sentinel(session, book)
    client = RecordingClient(_happy_path_responses())
    monkeypatch.setattr(notebook_qa, "DeepSeekClient", lambda *_a, **_kw: client)

    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="什么是极限？", history=[], allow_web=False,
    ))

    assert events[-1]["type"] == "verified_result"
    assert len(client.calls) >= 2
    stage1, stage2 = client.calls[0], client.calls[1]
    # 核心断言：Stage-1 请求里既没有哨兵字符串，也没有 DocumentIR 编号/种类。
    assert SENTINEL not in _flatten(stage1)
    assert '"kind": "document"' not in _flatten(stage1)
    stage1_ids = _stage_evidence_ids(stage1, "Notebook 正文证据（仅供参考）：\n")
    assert stage1_ids == ["N0"]
    assert all(evidence_id.startswith("N") for evidence_id in stage1_ids)
    # Stage-2 必须能看到 DocumentIR 证据。
    assert SENTINEL in _flatten(stage2)
    stage2_ids = _stage_evidence_ids(stage2, "证据：\n")
    assert "D0" in stage2_ids
    assert "N0" in stage2_ids

    verification = events[-1]["result"].process["verification"]
    assert verification["stage1_evidence_ids"] == ["N0"]
    assert "D0" in verification["stage2_evidence_ids"]
    assert verification["document_ir_evidence_count"] >= 1


def test_stage_isolation_proof_records_document_count_zero_without_sources(session, monkeypatch):
    """没有 DocumentIR 时，Stage-2 证据集与 Stage-1 相同，不能凭空造出 D 编号。"""

    book = _notebook_with_body(session)
    client = RecordingClient(_happy_path_responses())
    monkeypatch.setattr(notebook_qa, "DeepSeekClient", lambda *_a, **_kw: client)

    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="什么是极限？", history=[], allow_web=False,
    ))

    verification = events[-1]["result"].process["verification"]
    assert verification["document_ir_evidence_count"] == 0
    assert verification["stage1_evidence_ids"] == verification["stage2_evidence_ids"]


def test_gate_rejects_document_ir_id_not_approved_by_review(session, monkeypatch):
    """答案门禁不能因为 D 编号格式合法就接受它。"""

    book = _notebook_with_body(session)
    _document_with_sentinel(session, book)
    responses = _happy_path_responses()
    # answer gate 尝试用 DocumentIR 的 D0 支撑结论，但 review 只支持了 N0。
    responses[4] = {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                                "review_claim_ids": ["claim-1"], "evidence_ids": ["D0"], "source_ids": []}]}
    client = RecordingClient(responses)
    monkeypatch.setattr(notebook_qa, "DeepSeekClient", lambda *_a, **_kw: client)

    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="什么是极限？", history=[], allow_web=False,
    ))

    result = events[-1]["result"]
    assert result.reviews[-1]["evidence_ids"] == []
    assert "未核实" in result.answer
    assert notebook_qa.claims_for_answer(result)[0]["chunk_indexes"] == []


def test_claims_map_document_evidence_to_merged_chunk_indexes(session, monkeypatch):
    """D 编号必须映射到合并 chunks 中 DocumentIR 片段的下标，不能与 N 混用。"""

    book = _notebook_with_body(session)
    _document_with_sentinel(session, book)
    responses = _happy_path_responses()
    responses[1] = {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                                "evidence_ids": ["N0", "D0"], "needs_web": False}]}
    responses[4] = {"claims": [{"claim": "极限描述函数附近的变化趋势", "verdict": "supported",
                                "review_claim_ids": ["claim-1"],
                                "evidence_ids": ["N0", "D0"], "source_ids": []}]}
    client = RecordingClient(responses)
    monkeypatch.setattr(notebook_qa, "DeepSeekClient", lambda *_a, **_kw: client)

    events = list(notebook_qa.run_notebook_answer(
        session, notebook_id=book.id, revision=book.document_revision,
        question="什么是极限？", history=[], allow_web=False,
    ))

    result = events[-1]["result"]
    notebook_count = sum(1 for chunk in result.chunks if chunk.kind == "notebook")
    claims = notebook_qa.claims_for_answer(result)
    assert claims[0]["chunk_indexes"] == [0, notebook_count]
    assert result.chunks[notebook_count].kind == "document"
