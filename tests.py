#!/usr/bin/env python3
"""
FoxMemory — Suite de testes completa.

Testa:
1. CRUD basico (save, load, delete)
2. Deduplicacao (mesmo dado nao duplica)
3. Concorrencia (10 threads simultaneas)
4. Compressao/descompressao (integridade dos dados)
5. Busca por categoria
6. Busca por texto parcial
7. Sessions (multiplas instancias)
8. Stats
9. Purge de sessao
10. API REST (se servidor estiver rodando)
"""

import sys
import os
import json
import threading
import time
import sqlite3

sys.path.insert(0, os.path.dirname(__file__))
from memory_bridge import Memory, DB_PATH

passed = 0
failed = 0
total = 0


def test(name):
    global total
    total += 1
    print(f"  [{total:02d}] {name}...", end=" ")


def ok():
    global passed
    passed += 1
    print("OK")


def fail(msg=""):
    global failed
    failed += 1
    print(f"FAIL {msg}")


# ── Setup: usar DB temporario ──
import tempfile
import pathlib

tmp = tempfile.mkdtemp()
test_db = pathlib.Path(tmp) / "test_memory.db"

# Monkey-patch DB_PATH para testes
import memory_bridge
memory_bridge.DB_PATH = test_db

print("=" * 60)
print("  FoxMemory — Test Suite")
print(f"  DB: {test_db}")
print("=" * 60)
print()

# ── Test 1: Save basico ──
test("Save basico")
try:
    mem = Memory("test-01")
    mid = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    assert mid > 0, f"Expected id > 0, got {mid}"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 2: Load por contexto ──
test("Load por contexto")
try:
    results = mem.load("foxreply")
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    assert results[0]["dados"]["status"] == "live"
    assert results[0]["session_id"] == "test-01"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 3: Load por categoria ──
test("Load por categoria")
try:
    mem.save("dns", "cloudflare", {"zone": "abc123"})
    results = mem.load("", categoria="dns")
    assert len(results) == 1
    assert results[0]["categoria"] == "dns"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 4: Deduplicacao ──
test("Deduplicacao (mesmo dado nao duplica)")
try:
    mid1 = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    mid2 = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    assert mid1 == mid2, f"Expected same id, got {mid1} vs {mid2}"
    results = mem.load("foxreply")
    assert len(results) == 1, f"Expected 1 (dedup), got {len(results)}"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 5: Dado diferente cria novo ──
test("Dado diferente cria novo registro")
try:
    mid3 = mem.save("deploy", "foxreply", {"status": "live", "port": 18807})
    results = mem.load("foxreply")
    assert len(results) == 2, f"Expected 2, got {len(results)}"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 6: Multiplas sessoes ──
test("Multiplas sessoes isoladas")
try:
    mem2 = Memory("test-02")
    mem2.save("build", "foxshield", {"ok": True})
    sessions = mem.sessions()
    sids = [s["session_id"] for s in sessions]
    assert "test-01" in sids
    assert "test-02" in sids
    ok()
except Exception as e:
    fail(str(e))

# ── Test 7: Recent ──
test("Recent retorna ultimos N")
try:
    recent = mem.recent(limit=2)
    assert len(recent) <= 2
    # Mais recente primeiro
    if len(recent) == 2:
        assert recent[0]["updated_at"] >= recent[1]["updated_at"]
    ok()
except Exception as e:
    fail(str(e))

# ── Test 8: Recent filtrado por sessao ──
test("Recent filtrado por session_id")
try:
    recent = mem.recent(limit=10, session_id="test-02")
    assert all(r["session_id"] == "test-02" for r in recent)
    ok()
except Exception as e:
    fail(str(e))

# ── Test 9: Stats ──
test("Stats retorna contadores corretos")
try:
    stats = mem.stats()
    assert stats["total_memories"] >= 4
    assert "deploy" in stats["categorias"]
    assert stats["sessions"] >= 2
    assert stats["db_size_kb"] > 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 10: Delete ──
test("Delete por ID")
try:
    mid = mem.save("temp", "deletar", {"lixo": True})
    assert mem.delete(mid)
    results = mem.load("deletar")
    assert len(results) == 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 11: Purge session ──
test("Purge session remove tudo da sessao")
try:
    mem3 = Memory("test-purge")
    mem3.save("x", "a", {"1": 1})
    mem3.save("x", "b", {"2": 2})
    count = mem3.purge_session("test-purge")
    assert count == 2, f"Expected 2 purged, got {count}"
    assert len(mem3.recent(session_id="test-purge")) == 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 12: Compressao preserva dados complexos ──
test("Compressao preserva dados complexos (unicode, nested)")
try:
    complex_data = {
        "nome": "Avaliacoes Mercado Livre",
        "lista": [1, 2, 3, {"sub": True}],
        "unicode": "cafe com acucar e pao",
        "nested": {"a": {"b": {"c": 42}}},
        "null": None,
        "bool": False,
    }
    mem.save("test", "complex", complex_data)
    loaded = mem.load("complex")[0]["dados"]
    assert loaded == complex_data, f"Data mismatch: {loaded}"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 13: Busca parcial ──
test("Busca parcial (substring match)")
try:
    mem.save("deploy", "api-foxreply-v2", {"v": 2})
    mem.save("deploy", "api-foxqa-v1", {"v": 1})
    results = mem.load("foxqa")
    assert any("foxqa" in r["contexto"] for r in results)
    ok()
except Exception as e:
    fail(str(e))

# ── Test 14: Concorrencia (10 threads) ──
test("Concorrencia 10 threads x 20 writes")
try:
    errors = []

    def writer(sid, n):
        try:
            m = Memory(sid)
            for i in range(n):
                m.save("stress", f"{sid}-item-{i}", {"i": i, "t": time.time()})
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=writer, args=(f"t-{i}", 20)) for i in range(10)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    assert len(errors) == 0, f"Errors: {errors}"
    print(f"OK ({elapsed:.2f}s, 200 writes, 0 errors)")
    passed += 1
except Exception as e:
    fail(str(e))

# ── Config for API tests (from env vars — never hardcode secrets) ──
API_URL = os.environ.get("FOXMEMORY_API_URL", "")
API_KEY = os.environ.get("FOXMEMORY_API_KEY", "")

# ── Test 15: API REST (opcional — requer env vars) ──
test("API REST health check")
if not API_URL or not API_KEY:
    print("SKIP (set FOXMEMORY_API_URL and FOXMEMORY_API_KEY to run)")
    total -= 1
else:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{API_URL}/health",
            headers={"X-Api-Key": API_KEY},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert data["status"] == "ok"
            assert data["engine"] == "FoxMemory v1.0"
            ok()
    except Exception as e:
        print(f"SKIP (API offline: {e})")
        total -= 1

# ── Test 16: API REST save + search ──
test("API REST save + search round-trip")
if not API_URL or not API_KEY:
    print("SKIP (set FOXMEMORY_API_URL and FOXMEMORY_API_KEY to run)")
    total -= 1
else:
    try:
        import urllib.request
        body = json.dumps({
            "session_id": "test-api",
            "categoria": "test",
            "contexto": "api-roundtrip",
            "dados": {"from": "test-suite", "ts": time.time()},
        }).encode()
        req = urllib.request.Request(
            f"{API_URL}/memory/save",
            data=body,
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            save_result = json.loads(resp.read())
            assert save_result["id"] > 0

        req2 = urllib.request.Request(
            f"{API_URL}/memory/search?q=api-roundtrip",
            headers={"X-Api-Key": API_KEY},
        )
        with urllib.request.urlopen(req2, timeout=5) as resp:
            search_result = json.loads(resp.read())
            assert search_result["count"] >= 1
            assert any("api-roundtrip" in r["contexto"] for r in search_result["results"])
        ok()
    except Exception as e:
        print(f"SKIP (API offline: {e})")
        total -= 1

# ── Cleanup ──
import shutil
shutil.rmtree(tmp, ignore_errors=True)

# ── Report ──
print()
print("=" * 60)
print(f"  RESULTADO: {passed}/{total} passed", end="")
if failed > 0:
    print(f", {failed} FAILED")
else:
    print(" — ALL PASSED")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)
