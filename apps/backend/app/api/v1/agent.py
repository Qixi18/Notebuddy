"""HTTP/SSE adapter for Agent conversation turns."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.api import AgentMessageCreate
from app.services.agent_execution import (
    AgentMessageCommand,
    NotebookContextCommand,
    ReadingContextCommand,
    agent_message_events,
)

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable_encoder(event), ensure_ascii=False)}\n\n"


def _command(payload: AgentMessageCreate) -> AgentMessageCommand:
    reading = payload.reading_context
    notebook = payload.notebook_context
    return AgentMessageCommand(
        question=payload.question,
        scope=payload.scope,
        learning_goal=payload.learning_goal,
        material_id=payload.material_id,
        allow_web=payload.allow_web,
        allow_quiz=payload.allow_quiz,
        learning_mode=payload.learning_mode,
        idempotency_key=payload.idempotency_key,
        teacher_persona=str(payload.teacher_persona),
        reading_context=ReadingContextCommand(**reading.model_dump()) if reading else None,
        notebook_context=NotebookContextCommand(**notebook.model_dump()) if notebook else None,
    )


@router.post("/conversations/{conversation_id}/agent-messages")
def send_agent_message(
    conversation_id: str,
    payload: AgentMessageCreate,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    events = agent_message_events(conversation_id, _command(payload), db)

    def event_stream() -> Iterator[str]:
        for event in events:
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
