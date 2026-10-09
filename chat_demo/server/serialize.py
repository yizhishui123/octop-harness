"""Serialize harness stream events and LangChain messages into JSON-safe dicts.

The harness ``langgraph`` protocol emits dict events (see
``octop_harness.protocols.langgraph.AgentEventType``); most are already
JSON-safe. The exceptions handled here:

- ``tool_result`` carries raw ``ToolMessage`` objects -> flattened to
  ``{name, tool_call_id, status, content}`` dicts.
- ``state_snapshot`` carries the full graph state -> slimmed to the last
  message's ``usage_metadata`` / ``context_usage`` stamp.
- ``custom`` / ``hitl_required`` payloads are passed through a recursive
  best-effort JSON converter.
"""

from __future__ import annotations

import dataclasses
from typing import Any

_ROLE_BY_TYPE = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def json_safe(value: Any, *, _depth: int = 0) -> Any:
    """Best-effort conversion of arbitrary payloads to JSON-safe structures."""
    if _depth > 8:
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(v, _depth=_depth + 1) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value), _depth=_depth + 1)
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(), _depth=_depth + 1)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return json_safe(value.to_dict(), _depth=_depth + 1)
        except Exception:
            pass
    return str(value)


def flatten_content(content: Any) -> str:
    """Render message content (str or content-block list) as plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("type") == "thinking":
                    continue  # reasoning surfaces via additional_kwargs
                else:
                    parts.append(f"[{block.get('type', 'block')}]")
        return "".join(parts)
    return str(content) if content else ""


def message_to_dict(msg: Any) -> dict[str, Any]:
    """Serialize a LangChain ``BaseMessage`` for the history endpoint."""
    role = _ROLE_BY_TYPE.get(getattr(msg, "type", ""), getattr(msg, "type", "unknown"))
    additional = getattr(msg, "additional_kwargs", None) or {}
    out: dict[str, Any] = {
        "role": role,
        "content": flatten_content(getattr(msg, "content", "")),
    }
    reasoning = additional.get("reasoning_content")
    if reasoning:
        out["reasoning"] = str(reasoning)
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = [
            {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": json_safe(tc.get("args") or {})}
            for tc in tool_calls
        ]
    if role == "tool":
        out["name"] = getattr(msg, "name", "") or ""
        out["tool_call_id"] = getattr(msg, "tool_call_id", "") or ""
    return out


def _serialize_tool_result(event: dict[str, Any]) -> dict[str, Any]:
    results = []
    for msg in event.get("messages") or []:
        results.append(
            {
                "name": getattr(msg, "name", "") or (msg.get("name") if isinstance(msg, dict) else "") or "",
                "tool_call_id": getattr(msg, "tool_call_id", None)
                or (msg.get("tool_call_id") if isinstance(msg, dict) else "")
                or "",
                "status": getattr(msg, "status", "success"),
                "content": flatten_content(getattr(msg, "content", msg.get("content") if isinstance(msg, dict) else "")),
            }
        )
    return {"type": "tool_result", "node": event.get("node", ""), "results": results}


def _slim_state_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    """Keep only the last message's usage / context-usage stamp."""
    out: dict[str, Any] = {"type": "state_snapshot"}
    data = event.get("data")
    messages = data.get("messages") if isinstance(data, dict) else None
    if isinstance(messages, list) and messages:
        last = messages[-1]
        usage = getattr(last, "usage_metadata", None)
        if isinstance(usage, dict) and usage:
            out["usage"] = json_safe(usage)
        additional = getattr(last, "additional_kwargs", None) or {}
        context_usage = additional.get("context_usage")
        if context_usage:
            out["context_usage"] = json_safe(context_usage)
    return out


def serialize_event(event: Any) -> dict[str, Any]:
    """Normalize one harness stream event into a JSON-safe SSE payload."""
    if not isinstance(event, dict):
        return {"type": "custom", "data": json_safe(event)}
    event_type = event.get("type")
    if event_type == "tool_result":
        return _serialize_tool_result(event)
    if event_type == "state_snapshot":
        return _slim_state_snapshot(event)
    if event_type == "state_update":
        # Node-level bookkeeping the UI does not render; forward a slim marker.
        return {"type": "state_update", "node": event.get("node", "")}
    return {str(k): json_safe(v) for k, v in event.items()}
