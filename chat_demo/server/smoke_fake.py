"""In-process smoke test: exercise the SSE endpoints with a fake chat model.

Runs the FastAPI app via TestClient with ``CHAT_DEMO_FAKE_MODEL=1`` (see
``server.runtime.install_fake_model``) — no network or real API key needed.

Usage (from ``chat_demo/``)::

    ../.venv/bin/python -m server.smoke_fake
"""

from __future__ import annotations

import json
import os
import sys

# Provider detection only checks key presence; the fake model never calls out.
os.environ.setdefault("OPENAI_API_KEY", "sk-fake")
os.environ["CHAT_DEMO_FAKE_MODEL"] = "1"

from fastapi.testclient import TestClient

from server.main import app
from server.runtime import FAKE_REPLY


def main() -> int:
    failures = 0
    with TestClient(app) as client:
        resp = client.get("/api/agents")
        resp.raise_for_status()
        agents = resp.json()["agents"]
        assert agents, "expected at least one demo agent"
        agent_id = agents[0]["agent_id"]
        print(f"[ok] GET /api/agents -> {len(agents)} agent(s): {[a['name'] for a in agents]}")
        print(f"     models: {[m['ref'] for m in agents[0]['models']][:3]} ...")

        events: list[dict] = []
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"agent_id": agent_id, "message": "hi"},
        ) as stream:
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))

        types = [e.get("type") for e in events]
        print(f"[ok] POST /api/chat/stream -> {len(events)} frames, types seen: {sorted(set(types))}")
        if "thread" not in types or "token" not in types or types[-1] != "done":
            failures += 1
            print(f"[FAIL] expected thread/token frames and terminal done, got: {types}")
        thread_id = next(e["thread_id"] for e in events if e.get("type") == "thread")
        text = "".join(e.get("content", "") for e in events if e.get("type") == "token")
        if text != FAKE_REPLY:
            failures += 1
            print(f"[FAIL] token stream mismatch: {text!r}")

        resp = client.get(f"/api/threads/{thread_id}/history", params={"agent_id": agent_id})
        resp.raise_for_status()
        history = resp.json()["messages"]
        print(f"[ok] GET history -> {len(history)} message(s), roles: {[m['role'] for m in history]}")
        if len(history) < 2:
            failures += 1
            print("[FAIL] history should contain the user + assistant messages")

        resp = client.get(f"/api/threads/{thread_id}/context", params={"agent_id": agent_id})
        resp.raise_for_status()
        ctx = resp.json()
        print(f"[ok] GET context -> used={ctx['used_tokens']} max={ctx['max_tokens']} source={ctx['source']}")

        resp = client.post("/api/chat/stop", json={"agent_id": agent_id, "thread_id": thread_id})
        resp.raise_for_status()
        print("[ok] POST /api/chat/stop")

    if failures:
        print(f"\n{failures} check(s) FAILED")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
