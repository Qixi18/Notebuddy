from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import router
from app.db.migrate import migrate_database
from app.services.errors import ApplicationError


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate_database()
    yield


app = FastAPI(
    title="NoteBuddy Local API",
    version="0.1.0",
    description="Local course materials, page parsing, and retrieval preview API.",
    lifespan=lifespan,
)


@app.exception_handler(ApplicationError)
async def application_error_response(_: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Notebook-Settings-Token"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "NoteBuddy Local API", "version": "0.1.0"}
