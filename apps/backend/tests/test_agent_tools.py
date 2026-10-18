"""agent_tools 工具层测试：范围装配、课程隔离、锁定限制与建议-确认安全。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.agent_tools import build_tool_specs, execute_tool
from app.db.database import Base
from app.db.models import (
    Course,
    KnowledgeNode,
    KnowledgeProposal,
    Material,
    MaterialPage,
    Note,
    NoteSuggestion,
    PageBlock,
    RetrievalChunk,
)


def _build_world(db: Session) -> dict[str, str]:
    """两门课程：A（线性代数，含课件片段与两篇笔记）、B（大学英语，一篇笔记）。"""
    course_a = Course(name="线性代数")
    course_b = Course(name="大学英语")
    db.add_all([course_a, course_b])
    db.flush()

    node_a1 = KnowledgeNode(course_id=course_a.id, name="行列式")
    node_a2 = KnowledgeNode(course_id=course_a.id, name="矩阵")
    node_b1 = KnowledgeNode(course_id=course_b.id, name="阅读理解")
    db.add_all([node_a1, node_a2, node_b1])
    db.flush()

    material_a = Material(
        course_id=course_a.id, lecture_title="第1讲 行列式", original_filename="a.pptx",
        stored_filename="a.pptx", size_bytes=10, status="completed", page_count=1,
    )
    material_b = Material(
        course_id=course_b.id, lecture_title="第1讲 阅读技巧", original_filename="b.pptx",
        stored_filename="b.pptx", size_bytes=10, status="completed", page_count=1,
    )
    db.add_all([material_a, material_b])
    db.flush()

    page_a = MaterialPage(material_id=material_a.id, page_number=1, raw_text="行列式")
    page_b = MaterialPage(material_id=material_b.id, page_number=1, raw_text="阅读")
    db.add_all([page_a, page_b])
    db.flush()

    block_a = PageBlock(page_id=page_a.id, block_type="text", content="行列式是线性代数的基本工具，按对角线法则展开。", position=0)
    db.add(block_a)
    db.flush()
    db.add(RetrievalChunk(course_id=course_a.id, page_block_id=block_a.id, text="行列式是线性代数的基本工具，按对角线法则展开。"))

    note_a1 = Note(course_id=course_a.id, knowledge_node_id=node_a1.id, material_id=material_a.id, title="行列式", content_markdown="# 行列式\n\n## 定义\n\n用户写下的正文。\n\n## 判定\n\n保持不变。")
    note_a2 = Note(course_id=course_a.id, knowledge_node_id=node_a2.id, material_id=material_a.id, title="矩阵", content_markdown="# 矩阵")
    note_b1 = Note(course_id=course_b.id, knowledge_node_id=node_b1.id, material_id=material_b.id, title="阅读方法", content_markdown="# 阅读")
    db.add_all([note_a1, note_a2, note_b1])
    db.commit()
    return {
        "course_a": course_a.id, "course_b": course_b.id,
        "material_a": material_a.id, "material_b": material_b.id,
        "note_a1": note_a1.id, "note_a2": note_a2.id,
    }


def _world():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _build_world(db)
        yield db, ids


def test_tool_specs_follow_scope() -> None:
    locked = build_tool_specs(scope="note", editable_note=True)
    names_locked = {item["function"]["name"] for item in locked}
    assert "search_forest" not in names_locked
    assert "list_course_notes" not in names_locked
    assert "get_note_coverage" not in names_locked
    assert "propose_note_edits" in names_locked

    global_specs = build_tool_specs(scope="global", editable_note=True)
    names_global = {item["function"]["name"] for item in global_specs}
    assert {"search_forest", "get_note_coverage", "propose_note_edits", "propose_knowledge_node", "web_search"} <= names_global

    read_only = build_tool_specs(scope="global", editable_note=False)
    names_read_only = {item["function"]["name"] for item in read_only}
    assert "propose_note_edits" not in names_read_only
    assert "propose_knowledge_node" not in names_read_only


def test_search_course_hits_only_own_course() -> None:
    for db, ids in _world():
        outcome = execute_tool(db, course_id=ids["course_a"], name="search_course", arguments={"query": "行列式"})
        assert outcome.chunks, "自己课程的片段应命中"
        assert "第1讲 行列式" in outcome.payload_text

        other = execute_tool(db, course_id=ids["course_b"], name="search_course", arguments={"query": "行列式"})
        assert not other.chunks and "没有检索到" in other.payload_text, "不得跨课程命中"


def test_search_course_rejects_foreign_material() -> None:
    for db, ids in _world():
        outcome = execute_tool(db, course_id=ids["course_a"], name="search_course", arguments={"query": "行列式", "material_id": ids["material_b"]})
        assert "不属于当前课程" in outcome.payload_text


def test_read_note_respects_locked_scope() -> None:
    for db, ids in _world():
        outside = execute_tool(
            db, course_id=ids["course_a"], name="read_note", arguments={"note_id": ids["note_a2"]},
            scope="note", locked_note_id=ids["note_a1"],
        )
        assert "锁定" in outside.payload_text

        inside = execute_tool(
            db, course_id=ids["course_a"], name="read_note", arguments={},
            scope="note", locked_note_id=ids["note_a1"],
        )
        assert "《行列式》" in inside.summary and "用户写下的正文" in inside.payload_text

        course_scope = execute_tool(
            db, course_id=ids["course_a"], name="read_note", arguments={"note_id": ids["note_a2"]},
            scope="course", locked_note_id=None,
        )
        assert "《矩阵》" in course_scope.summary


def test_propose_note_edits_creates_pending_without_touching_content() -> None:
    for db, ids in _world():
        before = db.get(Note, ids["note_a1"]).content_markdown
        outcome = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "补充例子", "edits": [{"op": "append", "content": "补充：生活化例子。"}]},
            editable_note_id=ids["note_a1"],
        )
        db.flush()
        assert outcome.suggestions and outcome.suggestions[0]["type"] == "note_suggestion"
        suggestion = db.get(NoteSuggestion, outcome.suggestions[0]["id"])
        assert suggestion is not None and suggestion.status == "pending"
        assert "补充：生活化例子。" in suggestion.proposed_markdown
        assert db.get(Note, ids["note_a1"]).content_markdown == before, "工具绝不直接改正文"


def test_propose_note_edits_apply_deterministically() -> None:
    """结构化操作由后端确定性拼装：replace_section 保留标题行，只换该小节正文。"""
    for db, ids in _world():
        outcome = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "重写定义", "edits": [{"op": "replace_section", "anchor": "定义", "content": "重写后的定义。"}]},
            editable_note_id=ids["note_a1"],
        )
        db.flush()
        suggestion = db.get(NoteSuggestion, outcome.suggestions[0]["id"])
        proposed = suggestion.proposed_markdown
        assert "# 行列式" in proposed and "## 判定" in proposed and "保持不变。" in proposed, "其余小节原样保留"
        assert "重写后的定义。" in proposed and "用户写下的正文" not in proposed
        assert proposed.count("## 定义") == 1, "标题行保留且不重复"

        removed = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "删除判定", "edits": [{"op": "remove_section", "anchor": "判定"}]},
            editable_note_id=ids["note_a1"],
        )
        db.flush()
        removed_suggestion = db.get(NoteSuggestion, removed.suggestions[0]["id"])
        assert "## 判定" not in removed_suggestion.proposed_markdown and "保持不变。" not in removed_suggestion.proposed_markdown
        assert "## 定义" in removed_suggestion.proposed_markdown


def test_propose_note_edits_anchor_feedback() -> None:
    """锚点找不到/有歧义时，拒绝并给出候选标题，模型可自我纠正。"""
    for db, ids in _world():
        missing = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "r", "edits": [{"op": "replace_section", "anchor": "不存在的小节", "content": "x"}]},
            editable_note_id=ids["note_a1"],
        )
        assert "找不到标题" in missing.payload_text and "『定义』" in missing.payload_text

        ambiguous = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "r", "edits": [{"op": "replace_section", "anchor": "定", "content": "x"}]},
            editable_note_id=ids["note_a1"],
        )
        assert "匹配到多个小节" in ambiguous.payload_text


def test_propose_note_edits_restricts_target() -> None:
    for db, ids in _world():
        no_target = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "r", "edits": [{"op": "append", "content": "x"}]},
            editable_note_id=None,
        )
        assert "无法提交" in no_target.payload_text

        wrong_target = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={"rationale": "r", "edits": [{"op": "append", "content": "x"}], "note_id": ids["note_a2"]},
            editable_note_id=ids["note_a1"],
        )
        assert "只能对当前打开" in wrong_target.payload_text


def test_propose_note_edits_rejects_chat_contamination() -> None:
    """真实事故回归：agent 聊天回复（"建议已提交…点「采纳」"）混进操作 content。"""
    for db, ids in _world():
        contaminated = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={
                "rationale": "精简笔记",
                "edits": [{"op": "append", "content": "撤销建议已经提交啦，你点「采纳」它才会生效哦～"}],
            },
            editable_note_id=ids["note_a1"],
        )
        assert "对话" in contaminated.payload_text
        assert db.query(NoteSuggestion).filter_by(note_id=ids["note_a1"]).count() == 0


def test_propose_note_edits_rejects_duplicated_paragraphs() -> None:
    """真实事故回归：同一内容被叠加两次，最终正文出现重复段落。"""
    for db, ids in _world():
        duplicated = execute_tool(
            db, course_id=ids["course_a"], name="propose_note_edits",
            arguments={
                "rationale": "精简笔记",
                "edits": [
                    {"op": "append", "content": "这版删了两张表。"},
                    {"op": "append", "content": "这版删了两张表。"},
                ],
            },
            editable_note_id=ids["note_a1"],
        )
        assert "重复" in duplicated.payload_text
        assert db.query(NoteSuggestion).filter_by(note_id=ids["note_a1"]).count() == 0


def test_propose_knowledge_node_creates_pending() -> None:
    for db, ids in _world():
        outcome = execute_tool(
            db, course_id=ids["course_a"], name="propose_knowledge_node",
            arguments={"candidate_name": "克拉默法则", "candidate_summary": "用行列式解线性方程组", "rationale": "课件第2页提到", "confidence": 0.7},
            editable_note_id=ids["note_a1"],
        )
        db.flush()
        assert outcome.suggestions and outcome.suggestions[0]["type"] == "knowledge_proposal"
        proposal = db.get(KnowledgeProposal, outcome.suggestions[0]["id"])
        assert proposal is not None and proposal.status == "pending" and proposal.kind == "new"


def test_execute_tool_degrades_errors_to_text() -> None:
    for db, ids in _world():
        unknown = execute_tool(db, course_id=ids["course_a"], name="no_such_tool", arguments={})
        assert "不存在" in unknown.payload_text

        missing = execute_tool(db, course_id=ids["course_a"], name="read_note", arguments={"note_id": "not-exist"})
        assert "不存在" in missing.payload_text


def test_list_course_notes_returns_titles_and_stays_in_course() -> None:
    """回归：该工具曾因分发器统一塞 arguments 而每次 TypeError，导致「查有哪些笔记」无法返回。"""
    for db, ids in _world():
        outcome = execute_tool(db, course_id=ids["course_a"], name="list_course_notes", arguments={})
        assert "《行列式》" in outcome.payload_text and "《矩阵》" in outcome.payload_text
        assert "《阅读方法》" not in outcome.payload_text, "不得列出其他课程的笔记"


def test_every_tool_dispatches_without_signature_errors() -> None:
    """全工具分发回归：任何工具都不应因执行器签名不匹配而 TypeError。"""
    for db, ids in _world():
        calls: dict[str, dict] = {
            "search_course": {"query": "行列式"},
            "read_note": {},
            "list_course_notes": {},
            "search_forest": {"query": "阅读"},
            "get_note_coverage": {"material_id": ids["material_a"]},
            "explain_term": {"term": "行列式"},
            "web_search": {"query": "测试"},
            "propose_note_edits": {"rationale": "r", "edits": [{"op": "append", "content": "新段落"}]},
            "propose_knowledge_node": {"candidate_name": "x", "candidate_summary": "y", "rationale": "r"},
        }
        for name, arguments in calls.items():
            outcome = execute_tool(
                db, course_id=ids["course_a"], name=name, arguments=arguments,
                scope="global", locked_note_id=ids["note_a1"], editable_note_id=ids["note_a1"],
            )
            assert "TypeError" not in outcome.payload_text, f"{name}: {outcome.payload_text}"
            assert outcome.summary != f"工具 {name} 执行失败", f"{name}: {outcome.payload_text}"


def test_search_forest_covers_courses_and_skips_deleted() -> None:
    for db, ids in _world():
        found = execute_tool(db, course_id=ids["course_a"], name="search_forest", arguments={"query": "阅读"})
        assert "[大学英语]" in found.payload_text, "全局模式应能搜到其他课程的笔记"

        db.get(Course, ids["course_b"]).deleted_at = datetime.now(UTC)
        db.commit()
        after_delete = execute_tool(db, course_id=ids["course_a"], name="search_forest", arguments={"query": "阅读"})
        assert "没有匹配" in after_delete.payload_text, "已删除课程不得出现在全局搜索"
