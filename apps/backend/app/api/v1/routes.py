from fastapi import APIRouter

from app.api.v1 import (
    agent,
    assistant,
    backup,
    config,
    conversations,
    courses,
    feedback,
    forest,
    forest_imports,
    jobs,
    knowledge,
    materials,
    notebook,
    notes,
    terms,
)

router = APIRouter()
for module in (config, courses, materials, jobs, knowledge, notes, notebook, assistant, conversations, agent, feedback, backup, terms, forest, forest_imports):
    router.include_router(module.router)
