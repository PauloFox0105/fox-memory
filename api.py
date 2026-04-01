"""FoxMemory API — Shared memory bridge for Claude Code + Claude.ai via MCP."""

import os
import json
import sys
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from memory_bridge import Memory

API_KEY = os.environ.get("FOXMEMORY_API_KEY", "foxmem_default_key")

app = FastAPI(
    title="FoxMemory API",
    description="Shared memory for Claude Code instances + Claude.ai MCP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def _auth(authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    key = x_api_key or (authorization.replace("Bearer ", "") if authorization else None)
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class SaveRequest(BaseModel):
    session_id: str = "claude-web"
    categoria: str
    contexto: str
    dados: dict


class SaveResponse(BaseModel):
    id: int
    message: str


@app.get("/health")
def health():
    mem = Memory("api")
    stats = mem.stats()
    return {"status": "ok", "engine": "FoxMemory v1.0", "memories": stats["total_memories"], "db_size_kb": stats["db_size_kb"]}


@app.get("/memory/recent")
def recent(
    limit: int = Query(10, ge=1, le=100),
    session_id: str = Query(None),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    results = mem.recent(limit=limit, session_id=session_id)
    for r in results:
        del r["hash"]
    return {"results": results, "count": len(results)}


@app.get("/memory/search")
def search(
    q: str = Query(..., min_length=1),
    categoria: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    results = mem.load(q, categoria=categoria, limit=limit)
    for r in results:
        del r["hash"]
    return {"query": q, "results": results, "count": len(results)}


@app.post("/memory/save", response_model=SaveResponse)
def save(
    body: SaveRequest,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory(body.session_id)
    mid = mem.save(body.categoria, body.contexto, body.dados)
    return SaveResponse(id=mid, message=f"Saved {body.categoria}/{body.contexto}")


@app.get("/memory/sessions")
def sessions(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    return {"sessions": mem.sessions()}


@app.get("/memory/stats")
def stats(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    return mem.stats()


@app.delete("/memory/{memory_id}")
def delete(
    memory_id: int,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    ok = mem.delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": memory_id}
