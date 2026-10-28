"""Evaluate real public DocLayNet development pages without training models.

The official development package contains page PNGs and their source-PDF text
cells. This explicit manual runner can parse those images directly or wrap each
page as a raster-only PDF to exercise the scanned-PDF route. It always writes
to a new isolated output directory and leaves human review pending.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import pymupdf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import Base
from app.document_processing.service import create_parse_run, execute_parse_run, load_ir
from tests.notebook_fixtures import make_asset, make_notebook


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())


def _expected_text(json_path: Path) -> tuple[str, int]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cells = data.get("cells", [])
    ordered = sorted(
        cells,
        key=lambda cell: (
            float(cell.get("bbox", [0, 0])[1]),
            float(cell.get("bbox", [0, 0])[0]),
        ),
    )
    return " ".join(str(cell.get("text", "")) for cell in ordered), len(cells)


def _raster_pdf(png_path: Path, pdf_path: Path) -> None:
    with pymupdf.open(png_path) as image_doc:
        rect = image_doc[0].rect
    doc = pymupdf.open()
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(page.rect, filename=str(png_path))
    doc.save(pdf_path)
    doc.close()


def evaluate(
    input_root: Path, output: Path, parser: str, source_format: str, tier: str,
    per_category: int | None,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    samples_dir = input_root / "PNG"
    annotations = json.loads((input_root / "coco.json").read_text(encoding="utf-8"))
    images = annotations.get("images", [])
    if not images:
        raise SystemExit(f"No page images found in {input_root / 'coco.json'}")
    if per_category is not None:
        category_counts: Counter[str] = Counter()
        selected = []
        for item in images:
            category = str(item.get("doc_category", "unknown"))
            if category_counts[category] < per_category:
                selected.append(item)
                category_counts[category] += 1
        images = selected

    settings.data_dir = output / "data"
    settings.data_dir.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{(output / 'isolated.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)

    import os

    os.environ["NOTEBOOK_DOCUMENT_PARSER"] = parser
    os.environ["NOTEBOOK_MINERU_TIER"] = tier
    os.environ["NOTEBOOK_MINERU_IMAGE_ANALYSIS"] = "false" if tier == "flash" else "true"
    report: list[dict[str, object]] = []
    wrapper_dir = output / "raster-pdf-wrappers"
    if source_format == "raster-pdf":
        wrapper_dir.mkdir()

    with Session(engine, expire_on_commit=False) as db:
        notebook = make_notebook(db, None, title="DocLayNet public sample evaluation")
        db.commit()
        for index, item in enumerate(images, start=1):
            image_path = samples_dir / item["file_name"]
            metadata_path = input_root / "JSON" / f"{image_path.stem}.json"
            if not image_path.is_file() or not metadata_path.is_file():
                raise FileNotFoundError(f"Missing paired sample: {image_path} / {metadata_path}")
            source_path = image_path
            if source_format == "raster-pdf":
                source_path = wrapper_dir / f"{image_path.stem}.pdf"
                _raster_pdf(image_path, source_path)

            metadata = json.loads(metadata_path.read_text(encoding="utf-8")).get("metadata", {})
            expected, expected_cells = _expected_text(metadata_path)
            expected_cjk_count = sum("\u4e00" <= char <= "\u9fff" for char in expected)
            suspect_font_map = (
                item.get("doc_category") == "patents" and expected_cjk_count == 0
            )
            extension = source_path.suffix.lower()
            is_image = extension in {".png", ".jpg", ".jpeg", ".webp"}
            asset = make_asset(
                db,
                notebook,
                name=(f"{metadata.get('original_filename', image_path.name)}"
                      f"-p{metadata.get('page_no', index)}{extension}"),
                media_type="image" if is_image else "document",
                extension=extension,
                sha=_sha256(source_path),
            )
            asset.byte_size = source_path.stat().st_size
            db.flush()
            run = create_parse_run(db, asset=asset)
            db.commit()
            started = time.perf_counter()
            record: dict[str, object] = {
                "sample_id": f"D{index:02d}",
                "doc_category": item.get("doc_category"),
                "source_document": item.get("doc_name"),
                "source_page_number": item.get("page_no"),
                "source_png": str(image_path),
                "source_png_sha256": _sha256(image_path),
                "input_file": str(source_path),
                "input_sha256": _sha256(source_path),
                "parser": parser,
                "source_format": source_format,
                "mineru_tier": tier if parser == "mineru" else None,
                "parse_run_id": run.id,
                "ground_truth_text_cells": expected_cells,
                "ground_truth_reference_status": (
                    "suspect_source_pdf_font_mapping" if suspect_font_map
                    else "dataset_pdf_text_cells"
                ),
                "manual_assessment": "pending_human_review",
            }
            try:
                outcome = execute_parse_run(db, run.id, source_path=source_path)
                db.commit()
                document = load_ir(db, outcome.run)
                blocks = list(document.all_blocks())
                figures = [block for block in blocks if block.figure and block.figure.image_key]
                recognized = " ".join(
                    block.searchable_text() for block in blocks
                    if block.type not in {"image", "figure"}
                )
                expected_norm, recognized_norm = _normalise(expected), _normalise(recognized)
                expected_counts, recognized_counts = Counter(expected_norm), Counter(recognized_norm)
                char_recall = (
                    sum(min(count, recognized_counts[char]) for char, count in expected_counts.items())
                    / len(expected_norm) if expected_norm else None
                )
                record.update({
                    "status": outcome.run.status,
                    "quality_status": document.quality.status,
                    "generation_allowed": document.quality.generation_allowed,
                    "page_count": len(document.pages),
                    "page_statuses": [page.status for page in document.pages],
                    "block_counts_by_type": dict(Counter(block.type for block in blocks)),
                    "figure_count": len(figures),
                    "figure_files_exist": all(
                        (settings.data_dir / block.figure.image_key).is_file() for block in figures
                    ) if figures else None,
                    "source_spans_valid": bool(blocks) and all(
                        block.source is not None
                        and block.source.asset_id == asset.id
                        and block.source.page_number == block.page_number
                        for block in blocks
                    ),
                    "ground_truth_char_recall_approx": (
                        round(char_recall, 4) if char_recall is not None and not suspect_font_map else None
                    ),
                    "ground_truth_sequence_similarity_approx": round(
                        difflib.SequenceMatcher(None, expected_norm, recognized_norm,
                                                autojunk=True).ratio(), 4,
                    ) if expected_norm and not suspect_font_map else None,
                    "recognized_text_excerpt": recognized[:1200],
                    "warnings": [issue.code for issue in document.quality.issues],
                })
            except Exception as exc:
                db.rollback()
                record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            report.append(record)
            (output / "results.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(
                f"{record['sample_id']} {record['status']} "
                f"{record.get('quality_status', '')} "
                f"text-recall={record.get('ground_truth_char_recall_approx')}",
                flush=True,
            )
    engine.dispose()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse public DocLayNet development pages")
    cli.add_argument("--input-root", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--parser", required=True, choices=["native", "mineru"])
    cli.add_argument("--source-format", choices=["image", "raster-pdf"], default="image")
    cli.add_argument("--tier", choices=["flash", "standard"], default="flash")
    cli.add_argument("--per-category", type=int,
                     help="Select up to N pages from each document category")
    args = cli.parse_args()
    evaluate(args.input_root.resolve(), args.output.resolve(), args.parser,
             args.source_format, args.tier, args.per_category)
