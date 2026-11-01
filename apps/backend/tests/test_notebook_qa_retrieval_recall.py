"""P1-QA-11：Notebook 检索召回与资料隔离的离线基准。

这些用例不调用任何真实模型或网络，只验证"该找得到的一定找得到、不该串的一定不串"。
定量召回（Recall@k）在 docs/acceptance-notebook-qa.md 里记录，需要真实材料后人工补。
"""

from __future__ import annotations

from app.ai import notebook_qa
from app.notes.document import normalize_document
from app.notes.store import write_document
from app.retrieval import service as retrieval
from tests.notebook_fixtures import make_asset, make_notebook, persist_ir

pytest_plugins = ["tests.notebook_fixtures"]


def _long_body(db, sections: list[tuple[str, str]]):
    book = make_notebook(db, None, "长笔记")
    content = []
    for index, (heading, text) in enumerate(sections):
        content.append({"type": "heading", "attrs": {"level": 1, "blockId": f"h-{index}"},
                        "content": [{"type": "text", "text": heading}]})
        content.append({"type": "paragraph", "attrs": {"blockId": f"p-{index}"},
                        "content": [{"type": "text", "text": text}]})
    write_document(db, book, normalize_document({"type": "doc", "content": content}),
                   expected_revision=0, origin="autosave")
    db.commit()
    return book


def test_notebook_body_recall_finds_tail_section_of_long_document(session):
    """章节很多时，靠后的章节也必须能被召回（不能只看前几节）。"""

    sections = [(f"第 {index} 节", f"这一节讲普通内容 {index}，与问题无关。") for index in range(1, 41)]
    sections.append(("第 41 节", "拉格朗日中值定理说明存在一点使导数等于平均变化率。"))
    book = _long_body(session, sections)

    chunks = retrieval.retrieve_notebook_body(
        session, course_id=None, question="拉格朗日中值定理是什么？", notebook_id=book.id,
    )

    assert chunks, "尾部章节必须被召回"
    assert any("拉格朗日" in chunk.text for chunk in chunks)


def test_notebook_body_is_scoped_to_requested_notebook(session):
    book_a = _long_body(session, [("A 节", "矩阵的秩等于行阶梯形的非零行数。")])
    book_b = _long_body(session, [("B 节", "矩阵的秩等于行阶梯形的非零行数。")])

    chunks = retrieval.retrieve_notebook_body(
        session, course_id=None, question="矩阵的秩", notebook_id=book_a.id,
    )

    assert chunks
    assert {chunk.notebook_id for chunk in chunks} == {book_a.id}
    assert book_b.id not in {chunk.notebook_id for chunk in chunks}


def test_document_ir_candidates_bounded_in_sql(session, monkeypatch):
    """候选集必须有 SQL 上界：不能把整库解析块取回 Python 再排序。"""

    book = make_notebook(session, None, "有资料")
    asset = make_asset(session, book, "教材.pdf")
    persist_ir(session, book, asset)

    monkeypatch.setattr(retrieval, "DOCUMENT_CHUNK_CANDIDATE_LIMIT", 1)
    chunks = retrieval.retrieve_document_ir(
        session, course_id=None, question="极限的定义", limit=10,
    )

    assert len(chunks) <= 1


def test_document_ir_recall_survives_long_source(session):
    book = make_notebook(session, None, "长资料")
    asset = make_asset(session, book, "长教材.pdf")
    filler = [("无关章节", ["这一章只有占位内容，不含目标术语。" * 5]) for _ in range(30)]
    filler.append(("目标章节", ["柯西收敛准则给出数列收敛的充要条件。" * 3]))
    persist_ir(session, book, asset, sections=filler)

    chunks = notebook_qa._document_chunks(session, book, "柯西收敛准则的充要条件是什么？")

    assert chunks, "长资料尾部的命中块也必须召回"
    assert any("柯西收敛准则" in chunk.text for chunk in chunks)


def test_notebook_chunks_never_mix_document_chunks(session):
    """正文检索与原始资料检索必须是两个独立结果集（Stage-1 隔离的前提）。"""

    book = _long_body(session, [("正文", "极限描述函数在一点附近的变化趋势。")])
    asset = make_asset(session, book, "教材.pdf")
    persist_ir(session, book, asset, sections=[("教材", ["极限的 ε-δ 定义原文。" * 3])])

    notebook_chunks = notebook_qa._notebook_chunks(session, book, "极限的定义")
    document_chunks = notebook_qa._document_chunks(session, book, "极限的定义")

    assert notebook_chunks and all(chunk.kind == "notebook" for chunk in notebook_chunks)
    assert document_chunks and all(chunk.kind == "document" for chunk in document_chunks)
    assert not ({id(chunk) for chunk in notebook_chunks} & {id(chunk) for chunk in document_chunks})
