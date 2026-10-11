from fastapi import APIRouter

from app.api.v1 import (
    assistant,
    backup,
    config,
    conversations,
    courses,
    feedback,
    jobs,
    knowledge,
    materials,
    notebook,
    notes,
    terms,
)

router = APIRouter()
for module in (config, courses, materials, jobs, knowledge, notes, notebook, assistant, conversations, feedback, backup, terms):
    router.include_router(module.router)
