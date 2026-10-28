"""Generate synthetic test samples and run isolated real document parsers.

Run explicitly with --output pointing at a NEW directory; writes no user database.
The resulting machine report requires human review of every sample.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import Base
from app.document_processing.service import create_parse_run, execute_parse_run, load_ir
from tests.notebook_fixtures import make_asset, make_notebook

FONT = Path("C:/Windows/Fonts/msyh.ttc")
CASES = {
    "C01": "中文文字型 PDF", "C02": "公式 PDF", "C03": "扫描 PDF",
    "C04": "文字与图片混排 PDF", "C05": "表格 PDF", "C06": "电路图 PDF",
    "C07": "多页含空白页 PDF", "C08": "旋转页 PDF", "C09": "中文题目 PNG",
    "C10": "模糊旋转 JPG", "C11": "公式表格配图 PNG", "C12": "多视觉块 PDF",
}
EXPECTED = {
    "C01": {"pages": 1, "required_text": ["全加器", "输入"]},
    "C02": {"pages": 1, "equation_blocks": 2, "required_formula_text": ["E", "Cout"],
             "formula_semantics": ["E = m·c²", "Cout = AB + ACin + BCin"]},
    "C03": {"pages": 1, "required_text": ["全加器", "Cin"], "image_evidence": True},
    "C04": {"pages": 1, "required_text": ["全加器"], "image_evidence": True},
    "C05": {"pages": 1, "table_rows_at_least": 5, "table_columns_at_least": 5,
             "full_adder_truth_table": True},
    "C06": {"pages": 1, "figure_evidence": True},
    "C07": {"pages": 3, "empty_page_number": 2},
    "C08": {"pages": 1, "rotation_degrees": 90},
    "C09": {"pages": 1, "required_text": ["全加器", "Cin"], "image_evidence": True},
    "C10": {"pages": 1, "image_exif_orientation": 6, "image_dimensions": [650, 1000],
             "image_evidence": True},
    "C11": {"pages": 1, "equation_blocks": 1, "table_blocks": 1,
             "full_adder_truth_table": True, "figure_evidence": True},
    "C12": {"pages": 1, "figure_evidence": True, "image_evidence": True},
}
FULL_ADDER_TRUTH_TABLE = [
    ["A", "B", "Cin", "S", "Cout"],
    ["0", "0", "0", "0", "0"],
    ["0", "0", "1", "1", "0"],
    ["0", "1", "0", "1", "0"],
    ["0", "1", "1", "0", "1"],
    ["1", "0", "0", "1", "0"],
    ["1", "0", "1", "0", "1"],
    ["1", "1", "0", "0", "1"],
    ["1", "1", "1", "1", "1"],
]


class PeakRssMonitor:
    """Sample this process RSS while one explicit parse is running."""

    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.peak_mb: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        try:
            import psutil
        except ImportError:
            return self
        process = psutil.Process()

        def sample_once() -> None:
            try:
                current = process.memory_info().rss / 1024**2
                self.peak_mb = max(self.peak_mb or 0, current)
            except psutil.Error:
                self._stop.set()

        def monitor() -> None:
            while not self._stop.is_set():
                sample_once()
                self._stop.wait(self.interval_seconds)

        sample_once()
        self._thread = threading.Thread(target=monitor, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


def picture(kind: str) -> bytes:
    image = Image.new("RGB", (1000, 650), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 30)
    draw.text((50, 35), "学习材料：全加器输入与输出", font=font, fill="black")
    draw.text((50, 90), "输入 A B 和进位 Cin，计算输出 S 与 Cout。", font=font, fill="black")
    draw.text((50, 145), "Cout = AB + ACin + BCin", font=font, fill="black")
    if kind in {"table", "mixed"}:
        table_font = ImageFont.truetype(str(FONT), 17)
        row_height = 31
        top = 220
        for row in range(10):
            y = top + row * row_height
            draw.line((50, y, 550, y), fill="black", width=2)
        for x in range(50, 551, 100):
            draw.line((x, top, x, top + 9 * row_height), fill="black", width=2)
        rows = [("A", "B", "Cin", "S", "Cout")]
        for index in range(8):
            a, b, cin = (index >> 2) & 1, (index >> 1) & 1, index & 1
            rows.append((str(a), str(b), str(cin), str(a ^ b ^ cin),
                         str((a & b) | (a & cin) | (b & cin))))
        for row_index, cells in enumerate(rows):
            for column, value in enumerate(cells):
                draw.text((62 + column * 100, top + 5 + row_index * row_height),
                          value, font=table_font, fill="black")
    if kind in {"diagram", "mixed"}:
        draw.rectangle((625, 270, 825, 370), outline="black", width=5)
        draw.text((660, 300), "XOR", font=font, fill="black")
        draw.line((550, 320, 625, 320), fill="black", width=5)
        draw.line((825, 320, 940, 320), fill="black", width=5)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def generate_samples(directory: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for case in CASES:
        is_image = case in {"C09", "C10", "C11"}
        path = directory / f"{case}{'.jpg' if case == 'C10' else '.png' if is_image else '.pdf'}"
        if is_image:
            payload = picture("mixed" if case == "C11" else "diagram")
            if case == "C10":
                from PIL import ImageFilter
                with Image.open(io.BytesIO(payload)) as image:
                    exif = Image.Exif()
                    exif[274] = 6
                    image.filter(ImageFilter.GaussianBlur(1)).save(
                        path, quality=75, exif=exif,
                    )
            else:
                path.write_bytes(payload)
            files[case] = path
            continue
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_font(fontname="cjk", fontfile=str(FONT))
        if case != "C03":
            page.insert_text((45, 65), "全加器：输入 A、B 和进位", fontname="cjk", fontsize=22)
            page.insert_text((45, 100), "Cout = AB + ACin + BCin", fontsize=14)
        if case == "C02":
            page.insert_text((45, 145), "E = m·c²", fontsize=17)
        if case in {"C03", "C04", "C05", "C06", "C08", "C12"}:
            kind = "table" if case == "C05" else "diagram" if case == "C06" else "mixed"
            page.insert_image(pymupdf.Rect(45, 170, 555, 500), stream=picture(kind))
        if case == "C12":
            page.insert_image(pymupdf.Rect(55, 530, 290, 685), stream=picture("table"))
            page.insert_image(pymupdf.Rect(320, 530, 555, 685), stream=picture("diagram"))
        if case == "C07":
            doc.new_page(width=612, height=792)
            doc.new_page(width=612, height=792).insert_text((45, 80), "Third page", fontsize=16)
        if case == "C08":
            page.set_rotation(90)
        doc.save(path)
        doc.close()
        files[case] = path
    return files


def _expectation_checks(case: str, document, blocks, record: dict) -> dict[str, bool]:
    expected = EXPECTED[case]
    text = " ".join(block.searchable_text() for block in blocks).casefold()
    equations = [block for block in blocks if block.type == "equation"]
    tables = [block.table for block in blocks if block.type == "table" and block.table]
    checks = {
        "page_count": len(document.pages) == expected["pages"],
        "source_spans_valid": bool(record["source_spans_valid"]),
    }
    if "required_text" in expected:
        checks["required_text"] = all(token.casefold() in text for token in expected["required_text"])
    if "required_formula_text" in expected:
        formula_text = " ".join(record["equation_texts"]).casefold()
        checks["required_formula_text"] = all(
            token.casefold() in text or token.casefold() in formula_text
            for token in expected["required_formula_text"]
        )
    if "equation_blocks" in expected:
        checks["equation_blocks"] = len(equations) >= expected["equation_blocks"]
    if "formula_semantics" in expected:
        formulas = [str(item).casefold() for item in record["equation_texts"]]
        checks["equation_latex_present"] = (
            len(equations) >= len(expected["formula_semantics"])
            and all((block.latex or "").strip() for block in equations)
        )
        checks["cout_formula_terms"] = any(
            all(token in formula for token in ("cout", "ab", "acin", "bcin", "+"))
            for formula in formulas
        )
        checks["energy_formula_superscript"] = any(
            "e" in formula and "m" in formula and "c" in formula and "2" in formula
            and ("^" in formula or "²" in formula) and "\\wedge" not in formula
            for formula in formulas
        )
    if "table_blocks" in expected:
        checks["table_blocks"] = len(tables) >= expected["table_blocks"]
    if "table_rows_at_least" in expected:
        checks["table_rows"] = any(len(table.rows) >= expected["table_rows_at_least"]
                                   for table in tables)
    if "table_columns_at_least" in expected:
        checks["table_columns"] = any(
            max((len(row) for row in table.rows), default=0) >= expected["table_columns_at_least"]
            for table in tables
        )
    if expected.get("full_adder_truth_table"):
        checks["full_adder_truth_table"] = any(
            [[str(cell).strip() for cell in row] for row in table.rows]
            == FULL_ADDER_TRUTH_TABLE
            for table in tables
        )
    if expected.get("image_evidence"):
        checks["image_evidence"] = (
            record["image_block_count"] > 0 or record["figure_count"] > 0
        ) and record["figure_files_exist"]
    if expected.get("figure_evidence"):
        checks["figure_evidence"] = record["figure_count"] > 0
    if "empty_page_number" in expected:
        page_number = expected["empty_page_number"]
        checks["empty_middle_page"] = (
            len(document.pages) >= page_number
            and document.pages[page_number - 1].status == "empty"
        )
    if "rotation_degrees" in expected:
        checks["page_rotation"] = any(
            page.rotation == expected["rotation_degrees"] for page in document.pages
        )
    if "image_exif_orientation" in expected:
        checks["exif_orientation"] = record["exif_orientation"] == expected["image_exif_orientation"]
    if "image_dimensions" in expected:
        checks["image_dimensions"] = record["page_dimensions"][0] == expected["image_dimensions"]
    return checks


def execute(output: Path, parser: str, tier: str) -> None:
    output.mkdir(parents=True, exist_ok=False)
    samples = output / "samples"
    samples.mkdir()
    settings.data_dir = output / "isolated-data"
    settings.data_dir.mkdir()
    engine = create_engine(f"sqlite:///{(output / 'isolated.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    files = generate_samples(samples)
    os.environ["NOTEBOOK_DOCUMENT_PARSER"] = parser
    os.environ["NOTEBOOK_MINERU_TIER"] = tier
    os.environ["NOTEBOOK_MINERU_IMAGE_ANALYSIS"] = "true" if tier == "standard" else "false"
    report = []
    with Session(engine, expire_on_commit=False) as db:
        notebook = make_notebook(db, None)
        db.commit()
        for case, path in files.items():
            image = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            asset = make_asset(db, notebook, name=path.name,
                               media_type="image" if image else "document", extension=path.suffix)
            run = create_parse_run(db, asset=asset)
            db.commit()
            start = time.perf_counter()
            record = {"sample_id": case, "purpose": CASES[case], "file": str(path),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "parser": parser, "parser_version": None, "tier": tier,
                      "parse_run_id": run.id, "expected": EXPECTED[case],
                      "manual_assessment": "pending_human_review", "limitations": []}
            try:
                with PeakRssMonitor() as memory:
                    outcome = execute_parse_run(db, run.id, source_path=path)
                record["rss_peak_mb"] = round(memory.peak_mb, 1) if memory.peak_mb else None
                db.commit()
                doc = load_ir(db, outcome.run)
                blocks = list(doc.all_blocks())
                figures = [b for b in blocks if b.figure and b.figure.image_key]
                equations = [b for b in blocks if b.type == "equation"]
                tables = [b.table for b in blocks if b.type == "table" and b.table]
                image_blocks = [b for b in blocks if b.type == "image"]
                record.update({"status": run.status, "quality_status": doc.quality.status,
                               "generation_allowed": doc.quality.generation_allowed,
                               "parser_version": outcome.ir.parser_version,
                               "page_count": len(doc.pages),
                               "page_statuses": [p.status for p in doc.pages],
                               "page_rotations": [p.rotation for p in doc.pages],
                               "page_dimensions": [[p.width, p.height] for p in doc.pages],
                               "block_counts_by_type": dict(Counter(b.type for b in blocks)),
                               "equation_texts": [b.latex or b.text for b in equations],
                               "table_shapes": [[len(table.rows), max(
                                   (len(row) for row in table.rows), default=0,
                               )] for table in tables],
                               "figure_count": len(figures),
                               "figure_files_exist": all(
                                   (settings.data_dir / b.figure.image_key).is_file()
                                   for b in figures
                               ),
                               "image_block_count": len(image_blocks),
                               "exif_orientation": None,
                               "source_spans_valid": bool(blocks) and all(
                                   b.source and b.source.asset_id == asset.id
                                   and b.source.page_number == b.page_number for b in blocks),
                               "warnings": [i.message for i in doc.quality.issues],
                               "text_excerpt": " ".join(b.searchable_text() for b in blocks)[:1000]})
                if case == "C10":
                    with Image.open(path) as source:
                        record["exif_orientation"] = source.getexif().get(274)
                checks = _expectation_checks(case, doc, blocks, record)
                record["expectation_checks"] = checks
                record["expectations_passed"] = all(checks.values())
                record["limitations"] = [name for name, passed in checks.items() if not passed]
            except Exception as exc:
                db.rollback()
                record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            record["elapsed_seconds"] = round(time.perf_counter() - start, 3)
            record.setdefault("rss_peak_mb", None)
            report.append(record)
            (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{case}: {record['status']} {record.get('quality_status', '')}", flush=True)
    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parser", choices=["native", "mineru"], required=True)
    parser.add_argument("--tier", choices=["flash", "standard"], default="flash")
    args = parser.parse_args()
    execute(args.output.resolve(), args.parser, args.tier)
