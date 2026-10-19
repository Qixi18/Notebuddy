"""Shared contracts for the agent tool registry and implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.retrieval.service import RetrievedChunk

AgentScope = Literal["note", "course", "global"]


@dataclass
class ToolOutcome:
    summary: str
    payload_text: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    web_results: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
