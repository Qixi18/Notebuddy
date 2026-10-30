"""Conservative JSON output estimates, not provider tokenizer guarantees.

Teaching expansion, Tiptap envelopes and per-node source links all consume
output tokens. Keep headroom and recover observed truncation by splitting input,
without increasing the per-request spending limit.
"""

from __future__ import annotations

from typing import Any

from app.generation.context import block_chars

NOTEBOOK_GENERATION_MAX_OUTPUT_TOKENS = 20_000
TARGET_OUTPUT_TOKENS = 6_000
UNIT_OUTPUT_OVERHEAD = 256
MAX_BATCH_REQUESTS = 32


def block_output_tokens(block: dict[str, Any]) -> int:
    chars = block_chars(block) + len(block.get("latex") or "")
    figure = block.get("figure") or {}
    chars += len(figure.get("latex") or "")
    return 2 * chars + 192 + len(block.get("block_id") or "")


def unit_output_tokens(blocks: list[dict[str, Any]]) -> int:
    return UNIT_OUTPUT_OVERHEAD + sum(block_output_tokens(block) for block in blocks)


def partition_payload_units(units: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Preserve all blocks and order, splitting at original block boundaries.

    One indivisible oversized block is attempted once; observed truncation is
    reported explicitly rather than dropping or slicing its evidence.
    """
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    cost = 0
    for unit in units:
        part: list[dict[str, Any]] = []
        continuation = False
        for block in unit["blocks"]:
            extra = block_output_tokens(block) + (0 if part else UNIT_OUTPUT_OVERHEAD)
            if (current or part) and cost + extra > TARGET_OUTPUT_TOKENS:
                if part:
                    current.append(_unit_part(unit, part, continuation))
                    continuation = True
                    part = []
                batches.append(current)
                current, cost = [], 0
                extra = block_output_tokens(block) + UNIT_OUTPUT_OVERHEAD
            part.append(block)
            cost += extra
        if part:
            current.append(_unit_part(unit, part, continuation))
    if current:
        batches.append(current)
    return batches


def _unit_part(unit: dict[str, Any], blocks: list[dict[str, Any]], continuation: bool):
    return {**unit, "blocks": blocks, **({"intent": "extend", "continuation": True}
                                       if continuation else {})}


def split_payload_batch(units: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if len(units) > 1:
        middle = len(units) // 2
        return [units[:middle], units[middle:]]
    unit = units[0]
    blocks = unit["blocks"]
    if len(blocks) < 2:
        return []
    middle = len(blocks) // 2
    return [[_unit_part(unit, blocks[:middle], False)],
            [_unit_part(unit, blocks[middle:], True)]]
