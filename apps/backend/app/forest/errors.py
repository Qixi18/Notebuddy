"""Framework independent failures raised by Forest domain capabilities."""
from __future__ import annotations


class CurriculumOperationError(Exception):
    """A safe curriculum operation failure with an HTTP-neutral status hint."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
