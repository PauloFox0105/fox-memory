#!/usr/bin/env python3
"""
FoxMemory Bridge v3.0
SQLite thread-safe + remote sync + end-to-end encryption (AES-256-GCM).

Features:
  - Local SQLite with WAL mode for 10+ concurrent writers
  - Dual-write: local DB + remote REST API
  - E2E encryption: data encrypted before leaving the machine
  - Deduplication via SHA256 hash
  - zlib compression on local storage
  - Backward compatible: reads both encrypted and plaintext records

Usage:
    from memory_bridge import Memory
    mem = Memory(session_id="cc-01")
    mem.save("deploy", "my-app", {"status": "live"})
    results = mem.load("my-app")
"""

import sqlite3
import zlib
import json
import hashlib
import threading
import os
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "memory.db"
MASTER_KEY_PATH = Path(__file__).parent / ".master_key"
_local = threading.local()

# ── Configuration (override via environment) ──
REMOTE_API_URL = os.environ.get("FOXMEMORY_API_URL", "")
REMOTE_API_KEY = os.environ.get("FOXMEMORY_API_KEY", "")
REMOTE_SYNC = os.environ.get("FOXMEMORY_REMOTE_SYNC", "1") == "1" and bool(REMOTE_API_URL)
E2E_ENABLED = os.environ.get("FOXMEMORY_E2E", "1") == "1"


# ── AES-256-GCM Encryption ──────────────────────────────

def _load_master_key() -> bytes | None:
    """Load 256-bit master key from file."""
    try:
        raw = MASTER_KEY_PATH.read_text().strip()
        return base64.urlsafe_b64decode(raw)
    except Exception:
        return None


_MASTER_KEY = _load_master_key()


def _encrypt(plaintext: str) -> str:
    """Encrypt with AES-256-GCM. Returns base64(nonce + ciphertext + tag)."""
    if not _MASTER_KEY or not E2E_ENABLED:
        return plaintext
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    aesgcm = AESGCM(_MASTER_KEY)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return "E2E:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def _decrypt(data: str) -> str:
    """Decrypt AES-256-GCM string. Passes through non-encrypted data."""
    if not isinstance(data, str) or not data.startswith("E2E:"):
        return data
    if not _MASTER_KEY:
        raise ValueError("Cannot decrypt: master key not found")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.urlsafe_b64decode(data[4:])
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_MASTER_KEY)
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def _encrypt_dados(dados: dict) -> dict:
    """Encrypt dados payload into E2E envelope."""
    if not _MASTER_KEY or not E2E_ENABLED:
        return dados
    plaintext = json.dumps(dados, ensure_ascii=False, default=str)
    return {"_e2e": _encrypt(plaintext)}


def _decrypt_dados(dados: dict) -> dict:
    """Decrypt E2E envelope. Backward compatible with plaintext."""
    if isinstance(dados, dict) and "_e2e" in dados:
        return json.loads(_decrypt(dados["_e2e"]))
    return dados


# ── SQLite ───────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def _init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            categoria TEXT NOT NULL,
            contexto TEXT NOT NULL,
            dados BLOB NOT NULL,
            hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_categoria ON memories(categoria);
        CREATE INDEX IF NOT EXISTS idx_contexto ON memories(contexto);
        CREATE INDEX IF NOT EXISTS idx_session ON memories(session_id);
        CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup ON memories(hash);
    """)
    conn.commit()


# ── Remote Sync ──────────────────────────────────────────

def _sync_to_remote(session_id: str, categoria: str, contexto: str, dados: dict) -> bool:
    """Push encrypted memory to remote API."""
    if not REMOTE_SYNC:
        return False
    try:
        payload = json.dumps({
            "session_id": session_id,
            "categoria": categoria,
            "contexto": contexto,
            "dados": _encrypt_dados(dados),
        }).encode()
        req = urllib.request.Request(
            f"{REMOTE_API_URL}/memory/save",
            data=payload,
            headers={"X-Api-Key": REMOTE_API_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=5).getcode() in (200, 201)
    except Exception:
        return False


# ── Memory Class ─────────────────────────────────────────

class Memory:
    def __init__(self, session_id: str = "claude-01"):
        self.session_id = session_id
        _init_db()

    def _compress(self, data: dict) -> bytes:
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        return zlib.compress(raw, level=6)

    def _decompress(self, blob: bytes) -> dict:
        return json.loads(zlib.decompress(blob).decode("utf-8"))

    def _hash(self, categoria: str, contexto: str, dados: dict) -> str:
        content = f"{categoria}:{contexto}:{json.dumps(dados, sort_keys=True, default=str)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def save(self, categoria: str, contexto: str, dados: dict) -> int:
        """Save memory locally + sync encrypted to remote."""
        now = datetime.now(timezone.utc).isoformat()
        h = self._hash(categoria, contexto, dados)
        blob = self._compress(dados)
        conn = _get_conn()

        existing = conn.execute("SELECT id FROM memories WHERE hash = ?", (h,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE memories SET updated_at = ?, session_id = ? WHERE id = ?",
                (now, self.session_id, existing["id"]),
            )
            conn.commit()
            _sync_to_remote(self.session_id, categoria, contexto, dados)
            return existing["id"]

        cursor = conn.execute(
            """INSERT INTO memories (session_id, categoria, contexto, dados, hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.session_id, categoria, contexto, blob, h, now, now),
        )
        conn.commit()
        _sync_to_remote(self.session_id, categoria, contexto, dados)
        return cursor.lastrowid

    def load(self, query: str, categoria: str | None = None, limit: int = 20) -> list[dict]:
        """Search memories by text (context or category)."""
        conn = _get_conn()
        q = f"%{query}%"
        if categoria:
            rows = conn.execute(
                "SELECT * FROM memories WHERE categoria = ? AND contexto LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (categoria, q, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE contexto LIKE ? OR categoria LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (q, q, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def recent(self, limit: int = 10, session_id: str | None = None) -> list[dict]:
        """Last N memories, optionally filtered by session."""
        conn = _get_conn()
        if session_id:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? ORDER BY updated_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def sessions(self) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT session_id, COUNT(*) as count, MAX(updated_at) as last_active "
            "FROM memories GROUP BY session_id ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        cats = conn.execute(
            "SELECT categoria, COUNT(*) as c FROM memories GROUP BY categoria ORDER BY c DESC"
        ).fetchall()
        size_bytes = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
        return {
            "total_memories": total,
            "categorias": {r["categoria"]: r["c"] for r in cats},
            "db_size_kb": round(size_bytes / 1024, 1),
            "sessions": len(self.sessions()),
            "e2e_encryption": E2E_ENABLED and _MASTER_KEY is not None,
        }

    def delete(self, memory_id: int) -> bool:
        conn = _get_conn()
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return conn.total_changes > 0

    def purge_session(self, session_id: str) -> int:
        conn = _get_conn()
        cursor = conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["dados"] = self._decompress(d["dados"])
        return d


# ── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    mem = Memory(session_id=sys.argv[1] if len(sys.argv) > 1 else "claude-01")

    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        e2e = "ON (AES-256-GCM)" if (E2E_ENABLED and _MASTER_KEY) else "OFF"
        sync = "ON" if REMOTE_SYNC else "OFF"
        print(f"FoxMemory Bridge v3.0")
        print(f"  Remote: {REMOTE_API_URL or 'not configured'} (sync={sync})")
        print(f"  E2E: {e2e}")
        print()
        print("Usage:")
        print("  python3 memory_bridge.py stats")
        print("  python3 memory_bridge.py recent [N]")
        print("  python3 memory_bridge.py search <query>")
        print("  python3 memory_bridge.py sessions")
        print("  python3 memory_bridge.py save <cat> <ctx> <json>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "stats":
        print(json.dumps(mem.stats(), indent=2, ensure_ascii=False))
    elif cmd == "recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for r in mem.recent(limit=n):
            print(f"  [{r['session_id']}] {r['categoria']}/{r['contexto']} — {r['updated_at']}")
            print(f"    {json.dumps(r['dados'], ensure_ascii=False)[:120]}")
    elif cmd == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else ""
        for r in mem.load(q):
            print(f"  [{r['session_id']}] {r['categoria']}/{r['contexto']}")
            print(f"    {json.dumps(r['dados'], ensure_ascii=False)[:120]}")
    elif cmd == "sessions":
        for s in mem.sessions():
            print(f"  {s['session_id']}: {s['count']} memories, last: {s['last_active']}")
    elif cmd == "save":
        cat, ctx, raw = sys.argv[2], sys.argv[3], sys.argv[4]
        mid = mem.save(cat, ctx, json.loads(raw))
        print(f"Saved ID={mid}")
    else:
        print(f"Unknown command: {cmd}")
