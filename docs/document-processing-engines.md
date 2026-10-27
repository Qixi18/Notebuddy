# 文档解析引擎

NoteBuddy keeps one downstream `DocumentIR` contract. The built-in parser remains the default; optional engines plug into the same parse-run, quality, evidence, and generation flow.

## PaddleOCR

PaddleOCR PP-OCRv6 is available as an optional OCR engine for scanned PDF pages and uploaded images. `NOTEBOOK_OCR_ENGINE=auto` prefers PaddleOCR when it is installed, then falls back to RapidOCR or Tesseract. Set the variable to `rapidocr`, `tesseract`, or `none` to select a different path.

From `apps/backend`, install it with:

```powershell
uv sync --extra paddleocr
uv pip install paddlepaddle==3.2.0 --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

The first OCR request can initialize PaddleX and fetch model weights. Model inference runs locally in the backend process.

## MinerU

MinerU is an optional full document parser for layout-aware extraction, OCR, tables, formulas, charts, and Office/PDF files. Its public Content List V2 renderer is adapted into NoteBuddy blocks, then NoteBuddy continues to apply its own quality assessment and storage rules.

From `apps/backend`, install it and enable it in `.env`:

```powershell
uv sync --extra mineru
```

```dotenv
NOTEBOOK_DOCUMENT_PARSER=mineru
NOTEBOOK_MINERU_TIER=standard
NOTEBOOK_MINERU_IMAGE_ANALYSIS=true
```

MinerU runs locally in this integration; no remote parsing endpoint is configured. The first parse may download model weights and can use substantial disk, memory, and compute. `NOTEBOOK_DOCUMENT_PARSER=native` restores NoteBuddy's built-in PDF and Office parser.

The adapter currently preserves page numbers, text, headings, lists, tables, equations, and figure descriptions. MinerU's normalized bounding boxes and extracted image files are not yet copied into NoteBuddy's evidence store, so those details are not exposed as block-level locations in this first increment.

If NoteBuddy is later offered as an online service based on MinerU, review MinerU's additional license terms, including its attribution requirement for online services.
