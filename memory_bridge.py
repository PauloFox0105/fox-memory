#!/usr/bin/env python3
"""
Claude Code Shared Memory Bridge v1.0
Banco SQLite thread-safe para 10+ instancias compartilharem contexto.

Uso:
    from memory_bridge import Memory

    mem = Memory(session_id="claude-01")
    mem.save("deploy", "foxreply", {"status": "live", "commit": "abc123"})
    results = mem.load("foxreply")
    results = mem.load("deploy", categoria="deploy")
    mem.recent(limit=10)
"""

import sqlite3
import zlib
import json
import hashlib
import threading
import os
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "memory.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Thread-local SQLite connection with WAL mode for concurrent access."""
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
        """Salva memoria. Atualiza se mesmo hash ja existe."""
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
            return existing["id"]

        cursor = conn.execute(
            """INSERT INTO memories (session_id, categoria, contexto, dados, hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.session_id, categoria, contexto, blob, h, now, now),
        )
        conn.commit()
        return cursor.lastrowid

    def load(self, query: str, categoria: str | None = None, limit: int = 20) -> list[dict]:
        """Busca memorias por texto (contexto ou categoria). Case-insensitive."""
        conn = _get_conn()
        q = f"%{query}%"

        if categoria:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE categoria = ? AND contexto LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (categoria, q, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE contexto LIKE ? OR categoria LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (q, q, limit),
            ).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def recent(self, limit: int = 10, session_id: str | None = None) -> list[dict]:
        """Ultimas N memorias, opcionalmente filtradas por sessao."""
        conn = _get_conn()
        if session_id:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? ORDER BY updated_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def sessions(self) -> list[dict]:
        """Lista todas as sessoes com contagem de memorias."""
        conn = _get_conn()
        rows = conn.execute(
            """SELECT session_id, COUNT(*) as count,
                      MAX(updated_at) as last_active
               FROM memories GROUP BY session_id
               ORDER BY last_active DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Estatisticas do banco."""
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
        }

    def delete(self, memory_id: int) -> bool:
        """Deleta memoria por ID."""
        conn = _get_conn()
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return conn.total_changes > 0

    def purge_session(self, session_id: str) -> int:
        """Remove todas as memorias de uma sessao."""
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
        print("Uso:")
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
            print(f"  {s['session_id']}: {s['count']} memorias, ultimo: {s['last_active']}")
    elif cmd == "save":
        cat, ctx, raw = sys.argv[2], sys.argv[3], sys.argv[4]
        dados = json.loads(raw)
        mid = mem.save(cat, ctx, dados)
        print(f"Salvo ID={mid}")
    else:
        print(f"Comando desconhecido: {cmd}")
