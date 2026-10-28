"""Explicit local-model smoke check; uses only a temporary synthetic image."""

import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import settings
from app.document_processing.adapters.mineru import parse_document
from app.document_processing.adapters.pdf import ParseContext


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="notebuddy-mineru-image-") as temp:
        settings.data_dir = Path(temp) / "data"
        path = Path(temp) / "diagram.png"
        image = Image.new("RGB", (900, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, 350, 220), outline="black", width=5)
        draw.rectangle((550, 100, 800, 220), outline="black", width=5)
        draw.line((350, 160, 550, 160), fill="black", width=5)
        draw.text((130, 140), "INPUT", fill="black", stroke_width=1)
        draw.text((580, 140), "OUTPUT", fill="black", stroke_width=1)
        image.save(path)
        context = ParseContext(asset_id="smoke", parse_run_id="smoke-run", doc_type="image",
                               file_sha256="0" * 64, title="Diagram")
        result = parse_document(path, context)
        print(json.dumps({"parser": result.parser_name, "pages": result.page_count,
                          "blocks": [block.type for page in result.pages for block in page.blocks],
                          "figures": sum(bool(block.figure and block.figure.image_key)
                                         for page in result.pages for block in page.blocks)},
                         ensure_ascii=True))
        assert result.page_count == 1
        assert any(block.type == "figure" for block in result.pages[0].blocks), (
            "Diagram was not classified as a figure; inspect actual model output."
        )


if __name__ == "__main__":
    main()
