"""Shared fixtures for the Notebook/Document Processing test suite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import (
    Asset,
    Course,
    DocumentParseRun,
    Material,
    Notebook,
    NotebookAsset,
)
from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    PageIR,
    QualityReport,
    SourceSpan,
    TableData,
)
from app.document_processing.service import persist_existing_ir


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        yield db


def make_course(db: Session, name: str = "课程") -> Course:
    course = Course(name=name)
    db.add(course)
    db.flush()
    return course


def make_notebook(db: Session, course: Course | None, title: str = "笔记") -> Notebook:

    book = Notebook(
        id=str(uuid.uuid4()), course_id=course.id if course else None, title=title,
        tree_slot=0, display_order=0, is_default=True,
        document_json='{"schema_version":2,"doc":{"type":"doc","content":[]}}',
        document_revision=0,
    )
    db.add(book)
    db.flush()
    return book


def make_asset(
    db: Session, book: Notebook, name: str = "资料.pdf", *,
    media_type: str = "document", extension: str = ".pdf",
    sha: str | None = None,
) -> Asset:
    asset = Asset(
        id=str(uuid.uuid4()), source_type="user_upload", media_type=media_type,
        mime_type="application/pdf" if extension == ".pdf" else "image/png",
        extension=extension, original_name=name,
        storage_key=f"originals/{uuid.uuid4().hex}{extension}", byte_size=10,
        sha256=sha or uuid.uuid4().hex, state="ready",
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(asset)
    db.add(NotebookAsset(
        notebook_id=book.id, asset_id=asset.id, role="source_material",
        is_owner=True, created_at=datetime.now(UTC).replace(tzinfo=None),
    ))
    db.flush()
    return asset


def make_material(db: Session, book: Notebook, asset: Asset, title: str = "第 1 讲") -> Material:
    material = Material(
        id=str(uuid.uuid4()), asset_id=asset.id, notebook_id=book.id, course_id=None,
        lecture_title=title, original_filename=asset.original_name,
        stored_filename=f"{uuid.uuid4().hex}.pdf", size_bytes=10, status="completed",
        page_count=1,
    )
    db.add(material)
    db.flush()
    return material


def simple_ir(
    asset_id: str,
    run_id: str,
    *,
    sections: list[tuple[str, list[str]]] | None = None,
    doc_type: str = "pdf",
    quality_status: str = "complete",
) -> DocumentIR:
    """Build a small IR with one page and one heading section per entry."""

    sections = sections or [(
        "第一章 极限",
        [
            "极限的定义：当 x 趋近于 a 时，f(x) 趋近于 L。"
            "这是微积分中最基本的概念之一，用来描述函数在某一点附近的变化趋势。" * 3,
            "记作 lim_{x→a} f(x) = L。"
            "理解极限需要同时关注左极限与右极限，并区分存在与不存在的各种情形。" * 3,
        ],
    )]
    blocks: list[BlockIR] = []
    page_number = 1
    order = 0
    block_index = 0
    sections_meta = []
    for title, paragraphs in sections:
        block_index += 1
        heading = BlockIR(
            block_id=f"t{run_id[:4]}-p{page_number}-h{block_index}",
            page_number=page_number, order=order, global_order=order,
            type="heading", level=1, text=title,
            source=SourceSpan(asset_id=asset_id, page_number=page_number),
            extraction="native_text", confidence=1.0,
        )
        order += 1
        blocks.append(heading)
        section_block_ids = [heading.block_id]
        for text in paragraphs:
            block_index += 1
            block = BlockIR(
                block_id=f"t{run_id[:4]}-p{page_number}-b{block_index}",
                page_number=page_number, order=order, global_order=order,
                type="paragraph", text=text,
                source=SourceSpan(asset_id=asset_id, page_number=page_number),
                extraction="native_text", confidence=1.0,
            )
            order += 1
            blocks.append(block)
            section_block_ids.append(block.block_id)
        sections_meta.append((title, section_block_ids))
    page = PageIR(
        page_id=f"{run_id}-p1", page_number=1, width=600, height=800,
        extraction="native_text", status="parsed",
        text="\n".join(block.text for block in blocks),
        confidence=1.0, blocks=blocks,
    )
    from app.document_processing.normalization.sections import build_sections

    document = DocumentIR(
        document_id=asset_id, asset_id=asset_id, parse_run_id=run_id, doc_type=doc_type,
        parser_name="test", parser_version="1", config_version="test-v1",
        page_count=1, pages=[page],
        quality=QualityReport(status=quality_status, generation_allowed=True),
    )
    document.sections = build_sections(document, document_title="测试资料")
    return document


def persist_ir(
    db: Session, book: Notebook, asset: Asset, *, sections=None, doc_type="pdf",
) -> DocumentParseRun:
    run_id = str(uuid.uuid4())
    document = simple_ir(asset.id, run_id, sections=sections, doc_type=doc_type)
    outcome = persist_existing_ir(db, asset=asset, document=document)
    db.commit()
    return outcome.run


def add_table(document: DocumentIR) -> None:
    page = document.pages[0]
    order = max((block.order for block in page.blocks), default=0) + 1
    block = BlockIR(
        block_id=f"{document.parse_run_id[:8]}-table-1", page_number=1,
        order=order, global_order=order, type="table", text="x | f(x)\n0 | 1",
        table=TableData(rows=[["x", "f(x)"], ["0", "1"]], header_rows=1),
        source=SourceSpan(asset_id=document.asset_id, page_number=1),
        extraction="native_text", confidence=0.9,
    )
    page.blocks.append(block)


def make_sessionmaker(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
