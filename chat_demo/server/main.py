"""FastAPI entrypoint for the chat demo.

Run from the ``chat_demo/`` directory:

    uvicorn server.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routes import router

app = FastAPI(title="octop-harness chat demo")

# Vite dev server origin (the production build can also be served statically).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
