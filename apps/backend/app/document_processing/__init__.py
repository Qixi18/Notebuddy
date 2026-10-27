"""Document Processing: versioned parsing, Document IR, quality and provenance."""

from app.document_processing.ir import (
    BlockIR,
    DocumentIR,
    FigureData,
    PageIR,
    QualityIssue,
    QualityReport,
    SectionIR,
    SourceSpan,
    TableData,
)

__all__ = [
    "BlockIR",
    "DocumentIR",
    "FigureData",
    "PageIR",
    "QualityIssue",
    "QualityReport",
    "SectionIR",
    "SourceSpan",
    "TableData",
]
