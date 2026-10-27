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
    generation,
    jobs,
    knowledge,
    materials,
    notebook,
    terms,
)

router = APIRouter()
for module in (config, courses, materials, jobs, knowledge, notebook, generation, assistant, conversations, agent, feedback, backup, terms, forest, forest_imports):
    router.include_router(module.router)
