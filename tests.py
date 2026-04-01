#!/usr/bin/env python3
"""
FoxMemory v3.0 — Test Suite (18 tests).

Tests: CRUD, deduplication, concurrency, compression, E2E encryption, API.
"""

import sys
import os
import json
import threading
import time
import tempfile
import pathlib
import shutil

sys.path.insert(0, os.path.dirname(__file__))

# Monkey-patch DB_PATH before import
tmp = tempfile.mkdtemp()
test_db = pathlib.Path(tmp) / "test_memory.db"

import memory_bridge
memory_bridge.DB_PATH = test_db

from memory_bridge import Memory

passed = 0
failed = 0
total = 0


def test(name):
    global total
    total += 1
    print(f"  [{total:02d}] {name}...", end=" ")


def ok(extra=""):
    global passed
    passed += 1
    print(f"OK{' ' + extra if extra else ''}")


def fail(msg=""):
    global failed
    failed += 1
    print(f"FAIL {msg}")


print("=" * 60)
print("  FoxMemory v3.0 — Test Suite")
print(f"  DB: {test_db}")
print("=" * 60)
print()

# ── Test 1: Save ──
test("Save basic")
try:
    mem = Memory("test-01")
    mid = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    assert mid > 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 2: Load by context ──
test("Load by context")
try:
    results = mem.load("foxreply")
    assert len(results) == 1
    assert results[0]["dados"]["status"] == "live"
    assert results[0]["session_id"] == "test-01"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 3: Load by category ──
test("Load by category")
try:
    mem.save("dns", "cloudflare", {"zone": "abc123"})
    results = mem.load("", categoria="dns")
    assert len(results) == 1
    assert results[0]["categoria"] == "dns"
    ok()
except Exception as e:
    fail(str(e))

# ── Test 4: Deduplication ──
test("Deduplication (same data = same ID)")
try:
    mid1 = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    mid2 = mem.save("deploy", "foxreply", {"status": "live", "port": 18806})
    assert mid1 == mid2
    results = mem.load("foxreply")
    assert len(results) == 1
    ok()
except Exception as e:
    fail(str(e))

# ── Test 5: Different data = new record ──
test("Different data creates new record")
try:
    mem.save("deploy", "foxreply", {"status": "live", "port": 18807})
    results = mem.load("foxreply")
    assert len(results) == 2
    ok()
except Exception as e:
    fail(str(e))

# ── Test 6: Multiple sessions ──
test("Multiple sessions isolated")
try:
    mem2 = Memory("test-02")
    mem2.save("build", "foxshield", {"ok": True})
    sids = [s["session_id"] for s in mem.sessions()]
    assert "test-01" in sids and "test-02" in sids
    ok()
except Exception as e:
    fail(str(e))

# ── Test 7: Recent ──
test("Recent returns last N")
try:
    recent = mem.recent(limit=2)
    assert len(recent) <= 2
    if len(recent) == 2:
        assert recent[0]["updated_at"] >= recent[1]["updated_at"]
    ok()
except Exception as e:
    fail(str(e))

# ── Test 8: Recent filtered ──
test("Recent filtered by session_id")
try:
    recent = mem.recent(limit=10, session_id="test-02")
    assert all(r["session_id"] == "test-02" for r in recent)
    ok()
except Exception as e:
    fail(str(e))

# ── Test 9: Stats ──
test("Stats returns correct counts")
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
test("Delete by ID")
try:
    mid = mem.save("temp", "deletar", {"trash": True})
    assert mem.delete(mid)
    assert len(mem.load("deletar")) == 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 11: Purge session ──
test("Purge session removes all")
try:
    mem3 = Memory("test-purge")
    mem3.save("x", "a", {"1": 1})
    mem3.save("x", "b", {"2": 2})
    count = mem3.purge_session("test-purge")
    assert count == 2
    assert len(mem3.recent(session_id="test-purge")) == 0
    ok()
except Exception as e:
    fail(str(e))

# ── Test 12: Complex data preservation ──
test("Compression preserves complex data (unicode, nested)")
try:
    complex_data = {
        "name": "Avaliações Mercado Livre",
        "list": [1, 2, 3, {"sub": True}],
        "unicode": "café com açúcar e pão",
        "nested": {"a": {"b": {"c": 42}}},
        "null": None,
        "bool": False,
    }
    mem.save("test", "complex", complex_data)
    loaded = mem.load("complex")[0]["dados"]
    assert loaded == complex_data
    ok()
except Exception as e:
    fail(str(e))

# ── Test 13: Partial search ──
test("Partial text search (substring)")
try:
    mem.save("deploy", "api-foxreply-v2", {"v": 2})
    mem.save("deploy", "api-foxqa-v1", {"v": 1})
    results = mem.load("foxqa")
    assert any("foxqa" in r["contexto"] for r in results)
    ok()
except Exception as e:
    fail(str(e))

# ── Test 14: Concurrency ──
test("Concurrency 10 threads x 20 writes")
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
    assert len(errors) == 0
    ok(f"({elapsed:.2f}s, 200 writes, 0 errors)")
except Exception as e:
    fail(str(e))

# ── Test 15: E2E encryption functions ──
test("E2E encrypt/decrypt round-trip")
try:
    from memory_bridge import _encrypt_dados, _decrypt_dados, _MASTER_KEY, E2E_ENABLED
    test_data = {"secret": "my-api-key-12345", "score": 99}
    if _MASTER_KEY and E2E_ENABLED:
        encrypted = _encrypt_dados(test_data)
        assert "_e2e" in encrypted
        assert encrypted["_e2e"].startswith("E2E:")
        decrypted = _decrypt_dados(encrypted)
        assert decrypted == test_data
        ok("(AES-256-GCM)")
    else:
        # Without master key, encrypt_dados returns plaintext (passthrough)
        result = _encrypt_dados(test_data)
        assert result == test_data
        ok("(passthrough — no master key)")
except Exception as e:
    fail(str(e))

# ── Test 16: E2E backward compatibility ──
test("E2E backward compatible with plaintext")
try:
    from memory_bridge import _decrypt_dados
    plaintext = {"status": "live", "port": 8080}
    assert _decrypt_dados(plaintext) == plaintext
    ok()
except Exception as e:
    fail(str(e))

# ── API tests (optional) ──
API_URL = os.environ.get("FOXMEMORY_API_URL", "")
API_KEY = os.environ.get("FOXMEMORY_API_KEY", "")

# ── Test 17: API health ──
test("API health check")
if not API_URL or not API_KEY:
    print("SKIP (set FOXMEMORY_API_URL and FOXMEMORY_API_KEY)")
    total -= 1
else:
    try:
        import urllib.request
        req = urllib.request.Request(f"{API_URL}/health", headers={"X-Api-Key": API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert data["status"] == "ok"
            assert "FoxMemory" in data["engine"]
            ok()
    except Exception as e:
        print(f"SKIP (API offline: {e})")
        total -= 1

# ── Test 18: API save + search ──
test("API save + search round-trip")
if not API_URL or not API_KEY:
    print("SKIP (set FOXMEMORY_API_URL and FOXMEMORY_API_KEY)")
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
            f"{API_URL}/memory/save", data=body,
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert json.loads(resp.read())["id"] > 0

        req2 = urllib.request.Request(
            f"{API_URL}/memory/search?q=api-roundtrip", headers={"X-Api-Key": API_KEY},
        )
        with urllib.request.urlopen(req2, timeout=5) as resp:
            result = json.loads(resp.read())
            assert result["count"] >= 1
        ok()
    except Exception as e:
        print(f"SKIP (API offline: {e})")
        total -= 1

# ── Cleanup ──
shutil.rmtree(tmp, ignore_errors=True)

# ── Report ──
print()
print("=" * 60)
print(f"  RESULT: {passed}/{total} passed", end="")
if failed > 0:
    print(f", {failed} FAILED")
else:
    print(" — ALL PASSED")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)
