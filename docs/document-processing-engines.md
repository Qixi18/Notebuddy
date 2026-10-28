# 文档解析引擎

NoteBuddy keeps one downstream `DocumentIR` contract. The built-in parser remains the default; optional engines plug into the same parse-run, quality, evidence, and generation flow. Native PDF rendering uses PyMuPDF when installed and otherwise uses the base `pypdfium2` dependency, so scanned-page OCR does not depend on the optional MinerU package.

## PaddleOCR

PaddleOCR PP-OCRv6 is an optional OCR engine for scanned PDF pages and uploaded images. `NOTEBOOK_OCR_ENGINE=auto` prefers PaddleOCR when PaddlePaddle and PaddleOCR are installed, then falls back to RapidOCR or Tesseract. Set the variable to `paddleocr`, `rapidocr`, `tesseract`, or `none` to select a specific path. OCR initialization and inference failures are recorded on the page and block generation when the page could not be read.

From `apps/backend`, install it with:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-document'
uv sync --locked --extra paddleocr --extra mineru
uv pip install --python .venv-document/Scripts/python.exe paddlepaddle==3.2.0 --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

The first worker parse can initialize PaddleX and fetch model weights. Model inference runs locally in the backend process. The application checks PaddleOCR model initialization before choosing it for a parse; unavailable models fall through in `auto` mode or produce a blocking page status when explicitly selected.

RapidOCR is the smaller optional CPU fallback and can be installed independently:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-document'
uv sync --locked --extra rapidocr --extra mineru
```

When syncing the `.venv-document` environment used by `scripts/dev.ps1`, activate that environment first and use `uv sync --active --extra mineru --extra rapidocr` to retain both optional parsers.

## MinerU

MinerU is an optional full document parser for layout-aware extraction, OCR, tables, formulas, charts, and Office/PDF files. Its public Content List V2 renderer is adapted into NoteBuddy blocks, then NoteBuddy continues to apply its own quality assessment and storage rules.

From `apps/backend`, install it and enable it in `.env` (the startup script uses `.venv-document` when present):

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-document'
uv sync --locked --extra mineru
```

```dotenv
NOTEBOOK_DOCUMENT_PARSER=mineru
NOTEBOOK_MINERU_TIER=flash
NOTEBOOK_MINERU_IMAGE_ANALYSIS=false
```

MinerU runs locally in this integration; no remote parsing endpoint is configured. `flash` is the low-resource default: text PDFs can parse without a model, and scanned PDFs use the small ONNX layout/OCR models. `basic` and `standard` add deeper analysis; `standard` enables VLM reasoning and may require multi-gigabyte weights or a configured VLM service. Set a higher tier intentionally. `NOTEBOOK_DOCUMENT_PARSER=native` restores NoteBuddy's built-in PDF and Office parser.

The adapter preserves page numbers, text, headings, lists, tables, equations, and figure descriptions. Image/chart blocks retain normalized bounding boxes and a derived image crop in the parse run's evidence store. The document API returns a run-scoped image URL for preview; the original uploaded file remains unchanged. A configured vision model analyzes the crop and adds separate page-located figure/table/equation evidence blocks.

Selecting `NOTEBOOK_DOCUMENT_PARSER=mineru` is explicit: a missing or incompatible MinerU installation fails the parse with an actionable parser-unavailable error; it does not silently fall back to the native parser. Keep the single default in `.env.example` set to `native`.

If NoteBuddy is later offered as an online service based on MinerU, review MinerU's additional license terms, including its attribution requirement for online services.

## Vision model fallback

The optional OpenAI-compatible vision engine can describe diagrams, recover table structure, and transcribe formulas from uploaded images or scanned PDF pages. Configure `NOTEBOOK_VISION_BASE_URL`, `NOTEBOOK_VISION_MODEL`, and optionally `NOTEBOOK_VISION_API_KEY`; requests send the selected image to that provider. Keep it disabled when documents must remain local. Model output is marked as uncertain/partial evidence and should be checked against the retained original.
