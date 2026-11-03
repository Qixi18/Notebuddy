"""Test environment isolation.

Critical: the application resolves its SQLite database from
``NOTEBOOK_DATA_DIR`` at import time.  Without this override, migration tests
would create/upgrade ``<repo>/data/notebook.sqlite3`` — the user's real vault.
This file runs before test modules import the app, so every test process gets a
throw-away data directory.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.gettempdir()) / f"notebuddy-tests-{os.getpid()}"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["NOTEBOOK_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.setdefault("NOTEBOOK_GENERATOR", "offline-extractive")
os.environ.setdefault("NOTEBOOK_DOCUMENT_PARSER", "native")
os.environ.setdefault("NOTEBOOK_DOCUMENT_PROCESSING_ROUTE", "standard")
# Never let a test call a paid provider by accident.
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("TAVILY_API_KEY", "")
# Synthetic tariffs let mocked worker calls exercise the real budget guard;
# tests that cover missing configuration override these values explicitly.
_TEST_FX_DATE = datetime.now(UTC).date().isoformat()
for _key, _value in {
    "DEEPSEEK_MODEL": "deepseek-test",
    "DEEPSEEK_INPUT_COST_PER_MILLION": "1",
    "DEEPSEEK_OUTPUT_COST_PER_MILLION": "1",
    "DEEPSEEK_PRICE_VERSION": "test-tariff-1",
    "DEEPSEEK_PRICE_SOURCE": "https://test.invalid/pricing/text",
    "NOTEBOOK_VISION_MODEL": "vision-test",
    "NOTEBOOK_VISION_INPUT_COST_PER_MILLION": "1",
    "NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION": "1",
    "NOTEBOOK_VISION_MAX_IMAGE_TOKENS": "10000",
    "NOTEBOOK_VISION_PRICE_VERSION": "test-vision-tariff-1",
    "NOTEBOOK_VISION_PRICE_SOURCE": "https://test.invalid/pricing/vision",
    "NOTEBOOK_BUDGET_USD_CNY_RATE": "7.2",
    "NOTEBOOK_BUDGET_FX_RATE_SOURCE": "https://test.invalid/fx",
    "NOTEBOOK_BUDGET_FX_RATE_AS_OF": _TEST_FX_DATE,
    "NOTEBOOK_BUDGET_FX_BUFFER_PERCENT": "25",
}.items():
    os.environ[_key] = _value
