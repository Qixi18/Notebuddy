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
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.gettempdir()) / f"notebuddy-tests-{os.getpid()}"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["NOTEBOOK_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.setdefault("NOTEBOOK_GENERATOR", "offline-extractive")
os.environ.setdefault("NOTEBOOK_DOCUMENT_PARSER", "native")
# Never let a test call a paid provider by accident.
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("TAVILY_API_KEY", "")
