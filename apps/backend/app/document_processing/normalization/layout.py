"""Conservative geometric reading order without a mandatory layout model."""
from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.document_processing.engines.pdf_text import RawTextBlock


def _union(boxes):
    return [min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes)]


def order_text_blocks(blocks: list[RawTextBlock], page_width: float) -> list[RawTextBlock]:
    from app.document_processing.engines.pdf_text import RawTextBlock

    separated = []
    for block in blocks:
        if not block.lines or any(line.bbox is None for line in block.lines):
            separated.append(block)
            continue
        groups = []
        for line in block.lines:
            box = line.bbox
            for group in groups:
                other = _union([item.bbox for item in group])
                overlap = max(0, min(box[2], other[2]) - max(box[0], other[0]))
                width = max(1, min(box[2] - box[0], other[2] - other[0]))
                if overlap / width >= .25 or abs(box[0] - other[0]) < 12:
                    group.append(line)
                    break
            else:
                groups.append([line])
        separated.extend(RawTextBlock(lines=group, bbox=_union([line.bbox for line in group]))
                         for group in groups)
    if not separated or any(block.bbox is None for block in separated):
        return separated
    return _columns(separated, page_width)


def _columns(blocks, page_width):
    # Infer gutters from repeated body alignment, allowing a short centered
    # heading to cross them. Unioning every x-interval would erase that gutter.
    edges = sorted({x for block in blocks for x in (block.bbox[0], block.bbox[2])})
    candidates = []
    for low, high in pairwise(edges):
        cut = (low + high) / 2
        a = [block for block in blocks if block.bbox[2] <= cut]
        b = [block for block in blocks if block.bbox[0] >= cut]
        if len(a) < 2 or len(b) < 2:
            continue
        gap = min(block.bbox[0] for block in b) - max(block.bbox[2] for block in a)
        if gap >= 24:
            spanning = len(blocks) - len(a) - len(b)
            candidates.append((min(len(a), len(b)), -spanning, cut, a, b))
    if not candidates:
        return sorted(blocks, key=lambda block: (round(block.bbox[1], 1), block.bbox[0]))
    _, _, cut, left, right = max(candidates, key=lambda item: item[:2])
    spanning = sorted([block for block in blocks if block.bbox[0] < cut < block.bbox[2]],
                      key=lambda block: block.bbox[1])
    ordered = []
    for anchor in spanning:
        for column in (left, right):
            before = [block for block in column if (block.bbox[1] + block.bbox[3]) / 2 < anchor.bbox[1]]
            ordered.extend(_columns(before, page_width) if before else [])
            for block in before:
                column.remove(block)
        ordered.append(anchor)
    for column in (left, right):
        ordered.extend(_columns(column, page_width) if column else [])
    return ordered


def covered_area(boxes: list[list[float]]) -> float:
    """Rectangle union, so overlapping/duplicate images do not inflate coverage."""
    total = 0.0
    edges = sorted({x for box in boxes for x in (box[0], box[2])})
    for low, high in pairwise(edges):
        intervals = sorted((box[1], box[3]) for box in boxes if box[0] < high and box[2] > low)
        bottom, length = float("-inf"), 0.0
        for start, end in intervals:
            length += max(0, end - max(start, bottom))
            bottom = max(bottom, end)
        total += (high - low) * length
    return total
