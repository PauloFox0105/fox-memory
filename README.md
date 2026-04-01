# FoxMemory

Shared persistent memory system for multiple Claude Code instances + Claude.ai (via MCP).

## The Problem

When you run multiple Claude Code instances in parallel, each one starts fresh with no context about what the others did. If CC1 deployed FoxReply and CC2 needs to check its status, CC2 has no way to know. Same with Claude.ai — every new chat is a blank slate.

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
- **Tested**: 16 tests including 10-thread concurrency stress test

## Quick Start

### 1. Local Setup (Claude Code instances on same machine)

```bash
mkdir -p ~/.claude-shared-memory
cp memory_bridge.py ~/.claude-shared-memory/
```

Use in any Claude Code instance:

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-shared-memory"))
from memory_bridge import Memory

mem = Memory(session_id="cc-01")

# Save
mem.save("deploy", "my-app", {"status": "live", "url": "https://myapp.com"})

# Search
results = mem.load("my-app")

# Recent (all instances)
mem.recent(limit=10)

# Stats
mem.stats()
```

### 2. Remote Setup (API + Docker)

For multiple machines or Claude.ai access:

```bash
# Set your API key
export FOXMEMORY_API_KEY=your_secret_key_here

# Run with Docker
docker compose up -d --build
```

API endpoints:

```bash
# Health check
curl -H "X-Api-Key: $KEY" http://localhost:18820/health

# Save memory
curl -X POST -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:18820/memory/save \
  -d '{"session_id": "cc-01", "categoria": "deploy", "contexto": "my-app", "dados": {"status": "live"}}'

# Search
curl -H "X-Api-Key: $KEY" "http://localhost:18820/memory/search?q=my-app"

# Recent
curl -H "X-Api-Key: $KEY" "http://localhost:18820/memory/recent?limit=5"

# Stats
curl -H "X-Api-Key: $KEY" http://localhost:18820/memory/stats

# Sessions (which instances are active)
curl -H "X-Api-Key: $KEY" http://localhost:18820/memory/sessions

# Delete
curl -X DELETE -H "X-Api-Key: $KEY" http://localhost:18820/memory/42
```

### 3. Claude Code Skill

Create `~/.claude/skills/shared-memory.md`:

```markdown
---
name: shared-memory
description: Shared memory between CC instances. Use to persist state and share data between parallel CCs.
---

# Shared Memory

Before any task, check what other CCs did:
\```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-shared-memory"))
from memory_bridge import Memory
mem = Memory(session_id="cc-01")
print(mem.recent(limit=5))
\```

After completing important work, save it:
\```python
mem.save("deploy", "project-name", {"status": "live", "commit": "abc123"})
\```

Categories: deploy, dns, build, test, api, error, config
```

### 4. Connect Claude.ai via MCP

Once the API is running, register it as an MCP server in Claude.ai:

1. Go to Claude.ai > Settings > MCP Servers
2. Add new server with your API URL
3. Claude.ai can now query and save to the shared memory

## API Reference

### Python API

```python
mem = Memory(session_id="my-instance")

# Save — returns memory ID
mem.save(categoria, contexto, dados_dict) -> int

# Search — by text (context or category)
mem.load(query, categoria=None, limit=20) -> list[dict]

# Recent — last N memories
mem.recent(limit=10, session_id=None) -> list[dict]

# Sessions — list all active instances
mem.sessions() -> list[dict]

# Stats — database statistics
mem.stats() -> dict

# Delete — by ID
mem.delete(memory_id) -> bool

# Purge — remove all memories from a session
mem.purge_session(session_id) -> int
```

### Categories

Use consistent categories for better search:

| Category | When to use |
|----------|-------------|
| `deploy` | After deploying an app, container, or service |
| `dns` | After creating/changing DNS records |
| `build` | After build results (pass/fail) |
| `test` | After running test suites |
| `api` | API configurations, keys, endpoints |
| `error` | Errors that other instances should know about |
| `config` | Infrastructure or app configuration changes |
| `lead` | Business leads, customer data |

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

## Tests

```bash
python3 tests.py
```

Runs 16 tests:
- CRUD operations (save, load, delete, purge)
- Deduplication verification
- Multi-session isolation
- Complex data preservation (unicode, nested objects)
- 10-thread concurrency stress test (200 writes)
- REST API round-trip (if server is running)

## Files

```
fox-memory/
  memory_bridge.py    # Core engine (Python, zero dependencies)
  api.py              # REST API (FastAPI + uvicorn)
  tests.py            # Test suite (16 tests)
  Dockerfile          # Container image
  docker-compose.yml  # Docker deployment
  README.md           # This file
```

## License

MIT

## Author

Built by [Central Fox](https://centralfox.online) — AI tools for e-commerce.
