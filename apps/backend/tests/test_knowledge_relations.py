"""知识点关系的生成与归一化测试。

用例锁定这几条约束（早期版本 `knowledge_edges` 恒为 0 就是第一条被破坏）：
- 跨页引用的关系必须能连上：第 1 页提到的知识点在第 N 页才建立，也要成边；
- 同名/近同名（仅差空白、大小写、序号后缀）应合并为同一节点；
- 非法 relation_type、自引用、指向不存在节点的关系必须被过滤；
- 重复声明同一条边不应产生重复行。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    Course,
    KnowledgeEdge,
    KnowledgeNode,
    Material,
    MaterialPage,
    Note,
    NoteRevision,
    PageBlock,
)
from app.knowledge.extractor import (
    ensure_note,
    ensure_relations,
    find_node_by_name,
    find_or_create_node,
    normalize_name,
)
from app.notes.renderer import render_note_markdown


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _course(db: Session) -> Course:
    course = Course(name="线性代数")
    db.add(course)
    db.flush()
    return course


def _node(db: Session, course_id: str, name: str) -> KnowledgeNode:
    node = KnowledgeNode(course_id=course_id, name=name)
    db.add(node)
    db.flush()
    return node


# ---------- 归一化 ----------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("矩阵", "矩阵 "),
        ("矩阵", "  矩阵  "),
        ("矩阵", "矩阵（一）"),
        ("矩阵", "矩阵(上)"),
        ("矩阵", "矩阵【2】"),
        ("Matrix", "matrix"),
        ("MATRIX", "  matrix"),
        ("特征值", "特征值："),
    ],
)
def test_normalize_merges_equivalent_names(left: str, right: str) -> None:
    assert normalize_name(left) == normalize_name(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # 语义不同的名称绝不能被折叠，否则会错误合并知识点
        ("导数的定义", "导数的几何意义"),
        ("矩阵", "矩阵的秩"),
        ("特征值", "特征向量"),
        ("偏导数", "全微分"),
    ],
)
def test_normalize_keeps_distinct_names_apart(left: str, right: str) -> None:
    assert normalize_name(left) != normalize_name(right)


def test_normalize_handles_empty_and_whitespace() -> None:
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""
    assert normalize_name("　　") == ""


# ---------- 查找 ----------


def test_find_node_by_name_matches_normalized(db: Session) -> None:
    course = _course(db)
    node = _node(db, course.id, "矩阵")

    assert find_node_by_name(db, course.id, "  矩阵  ") is node
    assert find_node_by_name(db, course.id, "矩阵（一）") is node


def test_find_node_by_name_returns_none_when_absent(db: Session) -> None:
    course = _course(db)
    _node(db, course.id, "矩阵")

    assert find_node_by_name(db, course.id, "向量空间") is None
    assert find_node_by_name(db, course.id, "  ") is None


def test_find_node_by_name_is_scoped_to_course(db: Session) -> None:
    first = _course(db)
    second = Course(name="概率论")
    db.add(second)
    db.flush()
    _node(db, first.id, "矩阵")

    # 同名节点属于别的课程时不应命中
    assert find_node_by_name(db, second.id, "矩阵") is None


# ---------- 关系生成 ----------


def test_relations_are_created_for_existing_target(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    target = _node(db, course.id, "矩阵")

    ensure_relations(
        db,
        course.id,
        source,
        [{"target_name": "矩阵", "relation_type": "prerequisite", "confidence": 0.9}],
    )
    db.commit()

    edge = db.scalar(select(KnowledgeEdge))
    assert edge is not None
    assert edge.source_node_id == source.id
    assert edge.target_node_id == target.id
    assert edge.relation_type == "prerequisite"
    assert edge.confidence == pytest.approx(0.9)
    assert edge.course_id == course.id


def test_cross_page_relation_resolves_after_all_nodes_exist(db: Session) -> None:
    """回归核心 bug：目标节点「后于」源节点建立时，边仍要能生成。

    这正是原实现失败的场景——边建节点边连边，第 1 页的关系
    在目标节点尚未创建时被静默跳过，导致 knowledge_edges 恒为 0。
    """
    course = _course(db)

    # 先建源节点并立即尝试连边（模拟第一遍处理时的状态）
    source = _node(db, course.id, "矩阵的秩")
    ensure_relations(db, course.id, source, [{"target_name": "矩阵", "relation_type": "related"}])
    db.commit()
    # 此时目标还不存在，不应产生边，也不应凭空建节点
    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0
    assert db.scalar(select(func.count()).select_from(KnowledgeNode)) == 1

    # 目标节点稍后建立（模拟第二遍统一连边前所有节点已就位）
    target = _node(db, course.id, "矩阵")
    ensure_relations(
        db,
        course.id,
        source,
        [{"target_name": "矩阵", "relation_type": "related", "confidence": 0.8}],
    )
    db.commit()

    edge = db.scalar(select(KnowledgeEdge))
    assert edge is not None, "目标节点就位后关系必须能建立"
    assert edge.target_node_id == target.id


def test_invalid_relation_types_are_filtered(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    _node(db, course.id, "矩阵")

    ensure_relations(
        db,
        course.id,
        source,
        [
            {"target_name": "矩阵", "relation_type": "depends_on"},
            {"target_name": "矩阵", "relation_type": ""},
            {"target_name": "矩阵", "relation_type": "RELATED"},
            {"target_name": "矩阵", "relation_type": None},
        ],
    )
    db.commit()

    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0


def test_self_reference_is_skipped(db: Session) -> None:
    course = _course(db)
    node = _node(db, course.id, "矩阵")

    ensure_relations(db, course.id, node, [{"target_name": "矩阵", "relation_type": "related"}])
    db.commit()

    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0


def test_missing_target_does_not_create_phantom_node(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")

    ensure_relations(
        db, course.id, source, [{"target_name": "完全不存在的概念", "relation_type": "related"}]
    )
    db.commit()

    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0
    # 不能因为模型臆造了一个名字就凭空建节点
    assert db.scalar(select(func.count()).select_from(KnowledgeNode)) == 1


def test_duplicate_relation_is_not_inserted_twice(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    _node(db, course.id, "矩阵")
    payload = [{"target_name": "矩阵", "relation_type": "related", "confidence": 0.7}]

    ensure_relations(db, course.id, source, payload)
    ensure_relations(db, course.id, source, payload)
    ensure_relations(db, course.id, source, payload)
    db.commit()

    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 1


def test_same_pair_with_different_types_is_allowed(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    _node(db, course.id, "矩阵")

    ensure_relations(
        db,
        course.id,
        source,
        [
            {"target_name": "矩阵", "relation_type": "related"},
            {"target_name": "矩阵", "relation_type": "prerequisite"},
        ],
    )
    db.commit()

    types = set(db.scalars(select(KnowledgeEdge.relation_type)).all())
    assert types == {"related", "prerequisite"}


def test_relation_target_matched_through_normalization(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    target = _node(db, course.id, "矩阵")

    # 模型给出的目标名带序号后缀，仍应连到「矩阵」
    ensure_relations(
        db, course.id, source, [{"target_name": "矩阵（一）", "relation_type": "related"}]
    )
    db.commit()

    edge = db.scalar(select(KnowledgeEdge))
    assert edge is not None
    assert edge.target_node_id == target.id


def test_malformed_relations_are_ignored(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    _node(db, course.id, "矩阵")

    # 非 list、元素非 dict、缺少字段——都不应抛异常
    ensure_relations(db, course.id, source, None)
    ensure_relations(db, course.id, source, "not-a-list")
    ensure_relations(db, course.id, source, [1, "x", None, {}])
    ensure_relations(db, course.id, source, [{"relation_type": "related"}])
    ensure_relations(db, course.id, source, [{"target_name": "矩阵"}])
    ensure_relations(db, course.id, source, [{"target_name": "", "relation_type": "related"}])
    db.commit()

    assert db.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0


def test_confidence_must_be_numeric(db: Session) -> None:
    course = _course(db)
    source = _node(db, course.id, "矩阵的秩")
    _node(db, course.id, "矩阵")

    ensure_relations(
        db,
        course.id,
        source,
        [{"target_name": "矩阵", "relation_type": "related", "confidence": "很高"}],
    )
    db.commit()

    edge = db.scalar(select(KnowledgeEdge))
    assert edge is not None
    assert edge.confidence is None


def test_render_note_markdown_includes_sections() -> None:
    """关系之外，顺带锁住笔记渲染的基本结构。"""
    content = render_note_markdown(
        title="矩阵",
        summary="矩阵是数的矩形排列。",
        key_points=["行列", "元素"],
        methods=["矩阵乘法"],
        formulas=["$A_{m\\times n}$"],
        source_refs=[],
    )
    assert "矩阵" in content
    assert "行列" in content
    assert "矩阵乘法" in content
    assert "A_{m\\times n}" in content


def test_material_page_block_chain_is_intact(db: Session) -> None:
    """确保测试用的数据链路与真实模型一致（防止 fixture 漂移）。"""
    course = _course(db)
    material = Material(
        course_id=course.id,
        lecture_title="第一讲",
        original_filename="a.pptx",
        stored_filename="s.pptx",
        size_bytes=1,
    )
    db.add(material)
    db.flush()
    page = MaterialPage(material_id=material.id, page_number=1, raw_text="矩阵")
    db.add(page)
    db.flush()
    db.add(PageBlock(page_id=page.id, block_type="text", content="矩阵", position=0))
    db.commit()

    assert db.scalar(select(func.count()).select_from(PageBlock)) == 1
    assert db.scalar(select(func.count()).select_from(Note)) == 0


# ---------- 笔记唯一约束（本次上传失败的根因） ----------


def test_ensure_note_is_idempotent_for_same_node(db: Session) -> None:
    """同一知识点被重复调用时只应有一条笔记——回归 UNIQUE 约束崩溃。

    真实故障：一份 45 页课件里多个页面（封面、过渡页）解析出相同标题，
    `find_or_create_node` 复用了同一个节点，第二页再插入 Note 就撞上
    `UNIQUE constraint failed: notes.knowledge_node_id`，整个任务失败。
    """
    course = _course(db)
    node = _node(db, course.id, "向量与空间")

    ensure_note(db, course.id, node, "# 向量与空间\n\n第一版内容", [])
    ensure_note(db, course.id, node, "# 向量与空间\n\n第二页的内容", [])
    db.commit()

    assert db.scalar(select(func.count()).select_from(Note)) == 1
    note = db.scalar(select(Note))
    assert note is not None
    assert "第一版内容" in note.content_markdown


def test_ensure_note_survives_node_hit_by_multiple_pages(db: Session) -> None:
    """模拟封面页与内容页塌缩到同一节点：不应抛 IntegrityError。"""
    course = _course(db)

    # 两个页面归一化后同名 → find_or_create_node 返回同一个节点对象
    first = find_or_create_node(db, course.id, "向量与空间")
    second = find_or_create_node(db, course.id, "向量与空间（一）")
    assert first.id == second.id

    ensure_note(db, course.id, first, "# 封面\n\n本页为封面。", [])
    ensure_note(db, course.id, second, "# 第二页\n\n正文内容。", [])
    db.commit()

    assert db.scalar(select(func.count()).select_from(Note)) == 1


def test_ensure_note_records_revision_history(db: Session) -> None:
    """内容变化时递增修订号并留下历史，避免覆盖式更新丢失轨迹。"""
    course = _course(db)
    node = _node(db, course.id, "矩阵")

    assert ensure_note(db, course.id, node, "第一版", []).revision_number == 1
    assert ensure_note(db, course.id, node, "第二版", []).revision_number == 1
    db.commit()

    revisions = db.scalars(select(NoteRevision).order_by(NoteRevision.revision_number)).all()
    assert [r.revision_number for r in revisions] == [1]
    from app.db.models import NoteSuggestion
    assert db.scalar(select(NoteSuggestion)).proposed_markdown == "第二版"


def test_ensure_note_does_not_overwrite_locked_note(db: Session) -> None:
    """用户锁定过的笔记不应被 AI 结果覆盖。"""
    course = _course(db)
    node = _node(db, course.id, "矩阵")

    note = ensure_note(db, course.id, node, "AI 初版", [])
    note.user_locked = True
    db.flush()

    ensure_note(db, course.id, node, "AI 重跑版本", [])
    db.commit()

    assert note.content_markdown == "AI 初版"
    assert note.user_locked is True
