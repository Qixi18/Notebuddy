"""Explicit real-provider acceptance using a synthetic full-adder PDF and isolated data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.generation import create_generation_job
from app.core.config import settings
from app.db.database import Base
from app.db.models import Notebook, NotebookBlockSource, NotebookGenerationJob
from app.document_processing.service import create_parse_run, execute_parse_run
from app.notes.document import load_document
from app.schemas.generation import NotebookGenerationCreate
from app.workers import notebook_generation_worker as worker
from tests.notebook_fixtures import make_asset, make_notebook


def create_pdf(path: Path) -> None:
    diagram = Image.new("RGB", (1000, 470), "white")
    draw = ImageDraw.Draw(diagram)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 26)
    for box, label in [((270, 65, 430, 130), "XOR"), ((550, 65, 710, 130), "XOR"),
                       ((270, 210, 430, 275), "AND"), ((550, 210, 710, 275), "AND"),
                       ((790, 280, 950, 345), "OR")]:
        draw.rectangle(box, outline="black", width=4)
        draw.text((box[0] + 35, box[1] + 15), label, font=font, fill="black")
    for start, end in [((100, 80), (270, 80)), ((100, 115), (270, 115)),
                       ((430, 98), (550, 98)), ((100, 170), (550, 120)),
                       ((710, 98), (960, 98)), ((100, 80), (270, 220)),
                       ((100, 115), (270, 260)), ((430, 98), (550, 220)),
                       ((100, 170), (550, 260)), ((430, 245), (790, 300)),
                       ((710, 245), (790, 325)), ((950, 312), (990, 312))]:
        draw.line((start, end), fill="black", width=3)
    for pos, label in [((40, 60), "A"), ((40, 100), "B"), ((35, 155), "Cin"),
                       ((920, 60), "S"), ((920, 355), "Cout")]:
        draw.text(pos, label, fill="black", font=font)
    image_path = path.with_suffix(".png")
    diagram.save(image_path)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_font(fontname="cjk", fontfile="C:/Windows/Fonts/msyh.ttc")
    page.insert_text((45, 55), "全加器的逻辑与电路", fontname="cjk", fontsize=19)
    page.insert_text((45, 85), "输入 A、B 和进位 Cin；输出和 S 以及进位 Cout。", fontname="cjk", fontsize=12)
    page.insert_text((45, 110), "S = A XOR B XOR Cin", fontsize=13)
    page.insert_text((45, 132), "Cout = AB + ACin + BCin", fontsize=13)
    page.insert_text((45, 158), "真值表", fontname="cjk", fontsize=13)
    columns = [45, 110, 175, 240, 305, 370]
    for x in columns:
        page.draw_line((x, 175), (x, 355), color=(0, 0, 0))
    for y in range(175, 356, 20):
        page.draw_line((45, y), (370, y), color=(0, 0, 0))
    for i, label in enumerate(["A", "B", "Cin", "S", "Cout"]):
        page.insert_text((columns[i] + 10, 189), label, fontsize=10)
    for index in range(8):
        a, b, cin = (index >> 2) & 1, (index >> 1) & 1, index & 1
        for i, value in enumerate((a, b, cin, a ^ b ^ cin, (a & b) | (a & cin) | (b & cin))):
            page.insert_text((columns[i] + 15, 209 + index * 20), str(value), fontsize=10)
    page.insert_text((45, 385), "门电路示意图", fontname="cjk", fontsize=13)
    page.insert_image(pymupdf.Rect(45, 405, 565, 650), filename=str(image_path))
    doc.save(path)
    doc.close()


def run(output: Path, parser: str, generator: str) -> None:
    output.mkdir(parents=True, exist_ok=False)
    settings.data_dir = output / "data"
    settings.data_dir.mkdir()
    settings.notebook_generator = generator
    os.environ["NOTEBOOK_DOCUMENT_PARSER"] = parser
    os.environ["NOTEBOOK_MINERU_TIER"] = "standard"
    os.environ["NOTEBOOK_MINERU_IMAGE_ANALYSIS"] = "true"
    path = output / "full-adder.pdf"
    create_pdf(path)
    engine = create_engine(f"sqlite:///{(output / 'data' / 'notebook.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    worker.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    real_compose = worker.compose

    def capture_composition(*args, **kwargs):
        result = real_compose(*args, **kwargs)
        (output / "model-fragment.json").write_text(json.dumps(
            {"nodes": result.nodes, "source_map": result.source_map}, ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        return result

    worker.compose = capture_composition
    result = {"pdf": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "parser": parser, "generator": generator}
    with Session(engine, expire_on_commit=False) as db:
        book = make_notebook(db, None, title="全加器验收笔记")
        asset = make_asset(db, book, name=path.name)
        target = settings.data_dir / asset.storage_key
        target.parent.mkdir(parents=True)
        target.write_bytes(path.read_bytes())
        asset.byte_size = target.stat().st_size
        db.commit()
        run = create_parse_run(db, asset=asset)
        try:
            outcome = execute_parse_run(db, run.id)
            db.commit()
            result.update({"parse_run_id": run.id, "notebook_id": book.id, "asset_id": asset.id,
                           "quality": outcome.ir.quality.to_dict(),
                           "blocks": [b.to_dict() for p in outcome.ir.pages for b in p.blocks]})
            job = create_generation_job(book.id, NotebookGenerationCreate(asset_ids=[asset.id]),
                                        "full-adder-e2e", db)
            worker.claim_next_generation_job()
            worker.process_generation_job(job["id"])
            db.expire_all()
            row = db.get(NotebookGenerationJob, job["id"])
            result.update({"job_id": row.id, "job_status": row.status,
                           "error_code": row.error_code, "error_message": row.error_message,
                           "document": load_document(db.get(Notebook, book.id).document_json).content,
                           "source_count": len(db.scalars(select(NotebookBlockSource).where(
                               NotebookBlockSource.notebook_id == book.id)).all())})
        except Exception as exc:
            db.rollback()
            result.update({"error_type": type(exc).__name__, "error_message": str(exc)[:1000]})
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: result.get(k) for k in ("parser", "generator", "parse_run_id",
                          "notebook_id", "job_status", "error_code", "error_type", "error_message",
                          "source_count")}, ensure_ascii=True))
    engine.dispose()


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--parser", choices=["native", "mineru"], default="mineru")
    cli.add_argument("--generator", choices=["offline-extractive", "deepseek"], default="deepseek")
    args = cli.parse_args()
    run(args.output.resolve(), args.parser, args.generator)
