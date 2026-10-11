import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Course, Material, MaterialPage, Note, NoteSuggestion, PageBlock
from app.knowledge.extractor import extract_material_knowledge
from app.notes.service import update_note_as_user


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.knowledge.extractor.extract_page_draft",
                        lambda title, text, **kwargs: {"title": title, "summary": text})
    with Session(engine, autoflush=False) as session:
        yield session


def lecture(db, course, title, text):
    material = Material(course_id=course.id, lecture_title=title, original_filename="a.pptx",
                        stored_filename=title + ".pptx", size_bytes=1)
    db.add(material)
    db.flush()
    page = MaterialPage(material_id=material.id, page_number=1, title="矩阵", raw_text=text,
                        stable_location_key="slide:1")
    db.add(page)
    db.flush()
    db.add(PageBlock(page_id=page.id, block_type="text", content=text, position=0))
    db.flush()
    return material, page


def test_same_concept_keeps_independent_lecture_notes_and_retry_identity(db):
    course = Course(name="代数")
    db.add(course)
    db.flush()
    first, page = lecture(db, course, "第一讲", "矩阵定义")
    second, _ = lecture(db, course, "第二讲", "矩阵乘法")
    extract_material_knowledge(db, first.id)
    db.flush()
    note1 = db.scalar(select(Note).where(Note.material_id == first.id))
    update_note_as_user(db, note1, "用户补充：保留我", 1)
    db.flush()
    extract_material_knowledge(db, second.id)
    db.flush()
    note2 = db.scalar(select(Note).where(Note.material_id == second.id))
    assert note1.id != note2.id
    assert note1.knowledge_node_id == note2.knowledge_node_id
    assert note1.content_markdown == "用户补充：保留我"
    assert "矩阵乘法" in note2.content_markdown
    page.raw_text = "新的定义"
    extract_material_knowledge(db, first.id)
    db.flush()
    assert len(db.scalars(select(Note)).all()) == 2
    assert note1.content_markdown == "用户补充：保留我"
    assert db.scalar(select(NoteSuggestion).where(NoteSuggestion.note_id == note1.id)) is not None


@pytest.mark.parametrize("decision", ["confirm", "reject"])
def test_similar_candidate_is_readable_before_review(db, decision):
    from app.db.models import KnowledgeNode, KnowledgeProposal
    from app.knowledge.proposals import apply_proposal
    course = Course(name="代数")
    db.add(course)
    db.flush()
    material, page = lecture(db, course, "第一讲", "矩阵向量与线性计算")
    page.title = "矩阵计算"
    db.add(KnowledgeNode(course_id=course.id, name="矩阵运算", summary=page.raw_text))
    db.flush()
    extract_material_knowledge(db, material.id)
    db.flush()
    note = db.scalar(select(Note).where(Note.material_id == material.id))
    assert note is not None
    proposal = db.scalar(select(KnowledgeProposal).where(KnowledgeProposal.kind == "deepen"))
    assert proposal is not None
    body = note.content_markdown
    apply_proposal(db, proposal, decision=decision, note=None)
    db.flush()
    assert db.get(Note, note.id).content_markdown == body


def test_reparse_reuses_migrated_single_lecture_note(db):
    from app.db.models import KnowledgeNode
    course = Course(name="旧课程")
    db.add(course); db.flush()
    material, _ = lecture(db, course, "旧讲", "重新解析正文")
    node = KnowledgeNode(course_id=course.id, name="矩阵")
    db.add(node); db.flush()
    old = Note(course_id=course.id, knowledge_node_id=node.id, material_id=material.id,
               section_key="legacy:old", section_order=1, title="矩阵", user_locked=True,
               content_markdown="旧用户修改", revision_number=4)
    db.add(old); db.flush()
    identity = old.id
    extract_material_knowledge(db, material.id); db.flush()
    assert [n.id for n in db.scalars(select(Note)).all()] == [identity]
    assert old.content_markdown == "旧用户修改"
    assert old.revision_number == 4
    assert old.section_key == "slide:1"
