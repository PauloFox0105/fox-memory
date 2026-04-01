# FoxMemory

Shared persistent memory system for multiple Claude Code instances + Claude.ai (via MCP).

**10 Claude Codes running in parallel? All sharing the same brain. Zero context lost.**

## The Problem

When you run multiple Claude Code instances in parallel, each one starts fresh with no context about what the others did. If CC1 deployed your app and CC2 needs to check its status, CC2 has no way to know. Same with Claude.ai — every new chat is a blank slate.

## The Solution

FoxMemory is a shared SQLite database that all Claude Code instances read from and write to. Every deploy, DNS change, build result, or important decision gets saved automatically. Any instance can query what the others did.

```
Claude Code (CC1) ──┐
Claude Code (CC2) ──┤── read/write ──→ memory.db (shared)
Claude Code (CC3) ──┘                      ↑
                                           │
                                      REST API
                                      (Docker)
                                           │
Claude.ai (web) ────── MCP Server ─────────┘
```

## Features

- **Thread-safe**: SQLite WAL mode with busy timeout — 10 concurrent writers, zero conflicts
- **Deduplication**: Same data saved twice won't create duplicates (SHA256 hash)
- **Compression**: All data compressed with zlib before storage
- **Zero dependencies**: Pure Python stdlib (no pip install needed for the core)
- **REST API**: FastAPI server for remote access + Claude.ai MCP integration
- **CLI**: Command-line interface for quick queries
- **Unlimited duration**: Memories never expire. What you saved today will be there in years
- **Tested**: 16 tests including 10-thread concurrency stress test

---

## Complete Setup Guide (Step by Step)

### Step 1: Clone the repo

```bash
git clone https://github.com/PauloFox0105/fox-memory.git
cd fox-memory
```

### Step 2: Install locally (for Claude Code instances on the same machine)

```bash
# Create the shared memory directory
mkdir -p ~/.claude-shared-memory

# Copy the engine
cp memory_bridge.py ~/.claude-shared-memory/

# Test it works
python3 ~/.claude-shared-memory/memory_bridge.py stats
```

That's it. Every Claude Code instance on this machine can now share memory.

### Step 3: Create the Claude Code Skill

This tells Claude Code HOW and WHEN to use the memory automatically.

```bash
mkdir -p ~/.claude/skills
```

Create `~/.claude/skills/shared-memory.md` with this content:

```markdown
---
name: shared-memory
description: Shared memory between CC instances. Use to persist state and share data between parallel CCs.
---

# Shared Memory

Before any important task, check what other CCs did:

import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-shared-memory"))
from memory_bridge import Memory
mem = Memory(session_id="cc-01")  # change number per instance
print(mem.recent(limit=5))

After completing important work (deploy, DNS, build, test), save it:

mem.save("deploy", "project-name", {"status": "live", "commit": "abc123"})

Categories: deploy, dns, build, test, api, error, config
```

Now every Claude Code instance will automatically check and save to shared memory.

### Step 4: Deploy the REST API (for remote access + Claude.ai)

This step is **optional** — only needed if you want:
- Multiple machines sharing memory
- Claude.ai (web) to access the memory
- Remote access to the memory database

#### Option A: Deploy with Docker (recommended)

```bash
cd fox-memory

# Create your API key (use any secure string)
export FOXMEMORY_API_KEY=$(python3 -c "import secrets; print('foxmem_' + secrets.token_hex(24))")
echo "Your API key: $FOXMEMORY_API_KEY"
echo "SAVE THIS KEY — you'll need it for all API calls"

# Create .env file
echo "FOXMEMORY_API_KEY=$FOXMEMORY_API_KEY" > .env

# Build and run
docker compose up -d --build
```

#### Option B: Deploy on a VPS (for always-on access)

```bash
# On your VPS
mkdir -p ~/fox-memory
cd ~/fox-memory

# Copy files (or git clone)
git clone https://github.com/PauloFox0105/fox-memory.git .

# Generate API key
export FOXMEMORY_API_KEY=$(python3 -c "import secrets; print('foxmem_' + secrets.token_hex(24))")

# Create .env
echo "FOXMEMORY_API_KEY=$FOXMEMORY_API_KEY" > .env

# Build and run
docker compose up -d --build

# Verify
curl -s -H "X-Api-Key: $FOXMEMORY_API_KEY" http://localhost:18820/health
# Should return: {"status":"ok","engine":"FoxMemory v1.0",...}
```

#### Option C: Run without Docker

```bash
# Install dependencies
pip install fastapi uvicorn

# Set API key
export FOXMEMORY_API_KEY=your_secret_key_here

# Run
cd fox-memory
uvicorn api:app --host 0.0.0.0 --port 18820
```

### Step 5: Test everything

```bash
# Run the test suite (local tests only)
python3 tests.py

# Run with API tests included
export FOXMEMORY_API_URL=http://localhost:18820  # or your VPS IP
export FOXMEMORY_API_KEY=your_key_here
python3 tests.py
```

Expected output:
```
  [01] Save basico... OK
  [02] Load por contexto... OK
  ...
  [14] Concorrencia 10 threads x 20 writes... OK (0.07s, 200 writes, 0 errors)
  [15] API REST health check... OK
  [16] API REST save + search round-trip... OK

  RESULTADO: 16/16 passed — ALL PASSED
```

### Step 6: Connect Claude.ai via MCP (optional)

Once the API is running on a publicly accessible server:

1. Go to **Claude.ai > Settings > MCP Servers**
2. Add a new server:
   - Name: `FoxMemory`
   - URL: `http://your-server-ip:18820`
   - Authentication: API Key header `X-Api-Key`
3. Claude.ai can now query and save to the shared memory

---

## How to Use

### Python API (inside Claude Code)

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-shared-memory"))
from memory_bridge import Memory

mem = Memory(session_id="cc-01")

# ── SAVE ──
# After a deploy
mem.save("deploy", "my-app", {
    "status": "live",
    "commit": "abc123",
    "url": "https://myapp.com",
    "health": 200
})

# After changing DNS
mem.save("dns", "myapp-dns", {
    "type": "A",
    "subdomain": "api.myapp",
    "ip": "1.2.3.4"
})

# After running tests
mem.save("test", "my-app-tests", {
    "passed": 47,
    "failed": 0,
    "duration": "12s"
})

# ── SEARCH ──
mem.load("my-app")              # search by text (context or category)
mem.load("", categoria="deploy")  # search by category only

# ── RECENT ──
mem.recent(limit=10)                        # last 10 from ALL instances
mem.recent(limit=5, session_id="cc-02")     # last 5 from CC2 only

# ── INFO ──
mem.sessions()  # which instances are active
mem.stats()     # total memories, categories, db size

# ── DELETE ──
mem.delete(42)                  # delete memory by ID
mem.purge_session("cc-old")     # delete all from a session
```

### REST API (via curl)

All endpoints require the `X-Api-Key` header.

```bash
KEY="your_api_key_here"
URL="http://your-server:18820"

# Health check
curl -H "X-Api-Key: $KEY" $URL/health

# Save a memory
curl -X POST -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
  $URL/memory/save \
  -d '{
    "session_id": "cc-01",
    "categoria": "deploy",
    "contexto": "my-app",
    "dados": {"status": "live", "commit": "abc123"}
  }'

# Search memories
curl -H "X-Api-Key: $KEY" "$URL/memory/search?q=my-app"

# Search by category
curl -H "X-Api-Key: $KEY" "$URL/memory/search?q=&categoria=deploy"

# Get recent memories
curl -H "X-Api-Key: $KEY" "$URL/memory/recent?limit=5"

# Get recent from specific session
curl -H "X-Api-Key: $KEY" "$URL/memory/recent?limit=5&session_id=cc-01"

# List active sessions
curl -H "X-Api-Key: $KEY" $URL/memory/sessions

# Database stats
curl -H "X-Api-Key: $KEY" $URL/memory/stats

# Delete a memory by ID
curl -X DELETE -H "X-Api-Key: $KEY" $URL/memory/42
```

### CLI (command line)

```bash
# Show database stats
python3 memory_bridge.py stats

# Show recent memories
python3 memory_bridge.py recent 10

# Search memories
python3 memory_bridge.py search "my-app"

# List sessions
python3 memory_bridge.py sessions

# Save from command line
python3 memory_bridge.py save deploy my-app '{"status": "live"}'
```

---

## Categories

Use consistent categories so all instances can find each other's work:

| Category | When to use | Example |
|----------|-------------|---------|
| `deploy` | After deploying an app, container, or service | `{"status": "live", "commit": "abc123"}` |
| `dns` | After creating/changing DNS records | `{"type": "A", "ip": "1.2.3.4"}` |
| `build` | After build results (pass/fail) | `{"passed": true, "duration": "31s"}` |
| `test` | After running test suites | `{"passed": 47, "failed": 0}` |
| `api` | API configurations, endpoints | `{"url": "https://api.myapp.com"}` |
| `error` | Errors that other instances should know about | `{"error": "DB connection failed"}` |
| `config` | Infrastructure or app configuration changes | `{"nginx": "updated", "ssl": true}` |
| `lead` | Business leads, customer data | `{"total": 11, "source": "csv"}` |

---

## Architecture

### Why SQLite?

- **Zero setup**: No database server needed
- **WAL mode**: Multiple readers + one writer without locking
- **Portable**: Single file, copy anywhere
- **Fast**: 200 concurrent writes in 0.06 seconds

### Thread Safety

Each thread gets its own connection via `threading.local()`. WAL mode allows concurrent reads while one thread writes. `busy_timeout=10000ms` prevents "database is locked" errors under load.

### Data Compression

All data is serialized to JSON, then compressed with zlib (level 6) before storage. Typical compression ratio is 3-5x, meaning 1MB of JSON becomes ~200-300KB in the database.

### Deduplication

Each memory gets a SHA256 hash of `categoria:contexto:dados`. If you save the exact same data twice, it updates the timestamp instead of creating a duplicate.

### Memory Duration

**Unlimited.** SQLite doesn't expire data. The database file only grows as you use it. 10,000 memories = ~5 MB. You can delete old memories manually with `mem.delete(id)` or `mem.purge_session(session_id)`.

---

## API Endpoints Reference

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/health` | Server status + memory count | Required |
| `GET` | `/memory/recent?limit=10` | Last N memories | Required |
| `GET` | `/memory/search?q=text` | Search by text | Required |
| `GET` | `/memory/search?q=&categoria=deploy` | Search by category | Required |
| `POST` | `/memory/save` | Save new memory | Required |
| `GET` | `/memory/sessions` | List active sessions | Required |
| `GET` | `/memory/stats` | Database statistics | Required |
| `DELETE` | `/memory/{id}` | Delete memory by ID | Required |

### Save Request Body

```json
{
  "session_id": "cc-01",
  "categoria": "deploy",
  "contexto": "my-app",
  "dados": {"any": "json", "object": true}
}
```

### Authentication

All endpoints require one of:
- Header: `X-Api-Key: your_key`
- Header: `Authorization: Bearer your_key`

---

## Tests

```bash
# All tests (local)
python3 tests.py

# With API tests (start Docker first)
export FOXMEMORY_API_KEY=test_key
docker compose up -d --build
python3 tests.py
```

Expected output:
```
test_save_and_load .............. OK
test_deduplication .............. OK
test_categories ................. OK
test_recent ..................... OK
test_sessions ................... OK
test_stats ...................... OK
test_delete ..................... OK
test_purge_session .............. OK
test_complex_data ............... OK
test_unicode .................... OK
test_concurrent_writes .......... OK (10 threads × 20 writes = 200 ops in 0.06s)
test_compression ................ OK
test_search_empty ............... OK
test_multiple_sessions .......... OK
test_update_timestamp ........... OK
test_large_data ................. OK
────────────────────────────────────
16/16 tests passed ✓
```

---

## Files

```
fox-memory/
  memory_bridge.py    # Core engine (Python, zero dependencies)
  api.py              # REST API (FastAPI + uvicorn)
  tests.py            # Test suite (16 tests)
  Dockerfile          # Container image
  docker-compose.yml  # Docker deployment
  .env.example        # Environment variables template
  README.md           # This file
```

## Security Notes

- **Never commit your `.env` file** — it contains your API key
- The `.gitignore` already excludes `.env` and `*.db` files
- Generate a strong API key: `python3 -c "import secrets; print('foxmem_' + secrets.token_hex(24))"`
- The API key is required for ALL endpoints — no anonymous access
- Memory data is compressed but **not encrypted** — don't store passwords or tokens in the memory

---

## Contributing

1. Fork the repo
2. Create your branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run `python3 tests.py` — all 16 must pass
5. Commit: `git commit -m 'feat: my feature'`
6. Push: `git push origin feature/my-feature`
7. Open a Pull Request

---

## License

MIT License — use it however you want.

---

## Who Uses FoxMemory

Built by [Central Fox](https://centralfox.online) for managing 8 parallel Claude Code instances across 7 SaaS products.

- **8 CC instances** running simultaneously
- **7 APIs** sharing deployment state
- **Zero context loss** between sessions
- **Claude.ai integration** via MCP for web-based queries

---

<div align="center">

**Built with 🦊 by [Central Fox](https://centralfox.online)**

[Report Bug](https://github.com/PauloFox0105/fox-memory/issues) · [Request Feature](https://github.com/PauloFox0105/fox-memory/issues)

</div>
