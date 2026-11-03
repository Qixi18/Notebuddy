"""HTTP adapters for persisted document-processing results."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import DocumentParseRun
from app.schemas.document import DocumentBlockRead, DocumentIRRead, DocumentRunRead
from app.services.document_reads import (
    _document_payload as _document_payload_service,
)
from app.services.document_reads import (
    get_asset_document as get_asset_document_service,
)
from app.services.document_reads import (
    get_asset_document_run as get_asset_document_run_service,
)
from app.services.document_reads import (
    get_document_coverage as get_document_coverage_service,
)
from app.services.document_reads import (
    get_document_page_evidence as get_document_page_evidence_service,
)
from app.services.document_reads import (
    list_asset_parse_results as list_asset_parse_results_service,
)
from app.services.document_reads import (
    list_asset_parse_runs as list_asset_parse_runs_service,
)
from app.services.document_reads import (
    resolve_document_figure_image,
    resolve_document_page_render,
)

router = APIRouter()


@router.get("/assets/{asset_id}/parse-results")
def list_asset_parse_results(asset_id: str, db: Session = Depends(get_db)):
    return list_asset_parse_results_service(db, asset_id)


@router.get("/assets/{asset_id}/parse-runs", response_model=list[DocumentRunRead])
def list_asset_parse_runs(asset_id: str, notebook_id: str | None = None,
                          db: Session = Depends(get_db)):
    return list_asset_parse_runs_service(db, asset_id, notebook_id)


@router.get("/assets/{asset_id}/document", response_model=DocumentIRRead)
def get_asset_document(asset_id: str, notebook_id: str | None = None,
                       db: Session = Depends(get_db)):
    return get_asset_document_service(db, asset_id, notebook_id)


@router.get("/assets/{asset_id}/document/runs/{run_id}", response_model=DocumentIRRead)
def get_asset_document_run(asset_id: str, run_id: str, notebook_id: str | None = None,
                           db: Session = Depends(get_db)):
    return get_asset_document_run_service(db, asset_id, run_id, notebook_id)


@router.get("/assets/{asset_id}/document/pages/{page_number}/evidence",
            response_model=list[DocumentBlockRead])
def get_document_page_evidence(asset_id: str, page_number: int, notebook_id: str | None = None,
                               run_id: str | None = None, db: Session = Depends(get_db)):
    return get_document_page_evidence_service(
        db, asset_id, page_number, notebook_id=notebook_id, run_id=run_id,
    )


@router.get("/assets/{asset_id}/document/pages/{page_number}/render")
def get_document_page_render(asset_id: str, page_number: int, notebook_id: str | None = None,
                             run_id: str | None = None, db: Session = Depends(get_db)):
    path, media_type = resolve_document_page_render(
        db, asset_id, page_number, notebook_id=notebook_id, run_id=run_id,
    )
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "Content-Disposition": "inline"})


@router.get("/assets/{asset_id}/document/figures/{image_token}")
def get_document_figure_image(
    asset_id: str, image_token: str, notebook_id: str | None = None,
    run_id: str | None = None, db: Session = Depends(get_db),
):
    path, media_type = resolve_document_figure_image(
        db, asset_id, image_token, notebook_id=notebook_id, run_id=run_id,
    )
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/assets/{asset_id}/document/coverage")
def get_document_coverage(asset_id: str, notebook_id: str | None = None,
                          run_id: str | None = None, db: Session = Depends(get_db)):
    return get_document_coverage_service(
        db, asset_id, notebook_id=notebook_id, run_id=run_id,
    )


def _document_payload(db: Session, run: DocumentParseRun) -> dict:
    """Compatibility helper re-exported from the former aggregate route."""
    return _document_payload_service(db, run)
