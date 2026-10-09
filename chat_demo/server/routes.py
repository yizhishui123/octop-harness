"""HTTP routes: SSE chat streaming + history / context / agents endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from octop_harness.request import ChatRequest

from server.runtime import get_runtime
from server.serialize import message_to_dict, serialize_event

logger = logging.getLogger(__name__)

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class StreamBody(BaseModel):
    agent_id: str
    message: str
    thread_id: str | None = None
    model: str | None = None


class ResumeBody(BaseModel):
    agent_id: str
    thread_id: str
    decisions: list[dict[str, Any]]


class StopBody(BaseModel):
    agent_id: str
    thread_id: str


async def _sse(event_source: AsyncIterator[Any], *, first_frame: dict[str, Any] | None = None) -> AsyncGenerator[str, None]:
    """Relay harness events as SSE frames; append terminal done/error sentinels."""
    if first_frame is not None:
        yield f"data: {json.dumps(first_frame, ensure_ascii=False)}\n\n"
    try:
        async for event in event_source:
            yield f"data: {json.dumps(serialize_event(event), ensure_ascii=False)}\n\n"
        yield 'data: {"type":"done"}\n\n'
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # surface backend errors to the UI instead of a bare EOF
        logger.exception("stream failed")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/agents")
async def list_agents() -> dict[str, Any]:
    return {"agents": get_runtime().agents_payload()}


@router.post("/chat/stream")
async def chat_stream(body: StreamBody) -> StreamingResponse:
    runtime = get_runtime()
    if body.agent_id not in {a["agent_id"] for a in runtime.agents_payload()}:
        raise HTTPException(status_code=404, detail=f"unknown agent_id {body.agent_id!r}")
    thread_id = body.thread_id or uuid.uuid4().hex
    request = ChatRequest(messages=body.message, thread_id=thread_id, source="web", model=body.model)
    source = runtime.manager.stream(body.agent_id, request)
    return StreamingResponse(
        _sse(source, first_frame={"type": "thread", "thread_id": thread_id}),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/chat/resume")
async def chat_resume(body: ResumeBody) -> StreamingResponse:
    runtime = get_runtime()
    source = runtime.manager.resume_hitl(body.agent_id, body.thread_id, body.decisions)
    return StreamingResponse(_sse(source), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/chat/stop")
async def chat_stop(body: StopBody) -> dict[str, bool]:
    get_runtime().manager.cancel(body.agent_id, body.thread_id)
    return {"stopped": True}


@router.get("/threads/{thread_id}/history")
async def thread_history(thread_id: str, agent_id: str, limit: int = 50) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        messages = await runtime.manager.get_history(agent_id, thread_id, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}") from None
    return {"thread_id": thread_id, "messages": [message_to_dict(m) for m in messages]}


@router.get("/threads/{thread_id}/context")
async def thread_context(thread_id: str, agent_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        usage = await runtime.manager.get_context_usage(agent_id, thread_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}") from None
    return usage.to_dict()
