"""FoxMemory API v2.0 — REST API with E2E encryption support."""

import os
import json
import sys
import base64

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from memory_bridge import Memory

API_KEY = os.environ.get("FOXMEMORY_API_KEY", "foxmem_default_key")
DECRYPT_KEY = os.environ.get("FOXMEMORY_DECRYPT_KEY", "")

app = FastAPI(
    title="FoxMemory API",
    description="Shared memory for Claude Code instances + Claude.ai (E2E encrypted)",
    version="2.0.0",
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


def _try_decrypt(dados: dict, decrypt_key: str | None) -> dict:
    """Decrypt E2E envelope if valid decrypt key is provided."""
    if not decrypt_key or decrypt_key != DECRYPT_KEY or not DECRYPT_KEY:
        return dados
    if not isinstance(dados, dict) or "_e2e" not in dados:
        return dados
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        master_key = base64.urlsafe_b64decode(DECRYPT_KEY)
        encrypted = dados["_e2e"]
        if not encrypted.startswith("E2E:"):
            return dados
        raw = base64.urlsafe_b64decode(encrypted[4:])
        aesgcm = AESGCM(master_key)
        plaintext = aesgcm.decrypt(raw[:12], raw[12:], None)
        return json.loads(plaintext.decode("utf-8"))
    except Exception:
        return dados


def _process_results(results: list[dict], decrypt_key: str | None) -> list[dict]:
    for r in results:
        r.pop("hash", None)
        if "dados" in r:
            r["dados"] = _try_decrypt(r["dados"], decrypt_key)
    return results


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
    return {
        "status": "ok",
        "engine": "FoxMemory v2.0",
        "memories": stats["total_memories"],
        "db_size_kb": stats["db_size_kb"],
        "e2e": bool(DECRYPT_KEY),
    }


@app.get("/memory/recent")
def recent(
    limit: int = Query(10, ge=1, le=100),
    session_id: str = Query(None),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    x_decrypt_key: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    results = mem.recent(limit=limit, session_id=session_id)
    return {"results": _process_results(results, x_decrypt_key), "count": len(results)}


@app.get("/memory/search")
def search(
    q: str = Query(..., min_length=1),
    categoria: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    x_decrypt_key: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    results = mem.load(q, categoria=categoria, limit=limit)
    return {"query": q, "results": _process_results(results, x_decrypt_key), "count": len(results)}


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
    return {"sessions": Memory("api").sessions()}


@app.get("/memory/stats")
def stats(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    return Memory("api").stats()


@app.delete("/memory/{memory_id}")
def delete(
    memory_id: int,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _auth(authorization, x_api_key)
    mem = Memory("api")
    if not mem.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": memory_id}
