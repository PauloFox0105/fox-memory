# FoxMemory v3.0

Encrypted shared memory for multiple Claude Code instances + Claude.ai.

**10 CCs running in parallel? All sharing one brain. E2E encrypted. Zero context lost.**

## Architecture

```
CC1  ──┐
CC2  ──┤                                    ┌── SQLite local
CC3  ──┤── memory_bridge.py v3 ──┬── save ──┤   (plaintext, fast)
...    ┤   (AES-256-GCM)         │          └── REST API (encrypted)
CC10 ──┘                         │                    ↑
                                 │              HTTPS + TLS
                                 │                    │
Claude.ai ────── MCP ────────────┘     https://your-domain.com
```

## Features

- **E2E Encryption**: AES-256-GCM — data encrypted before leaving the machine
- **Dual-write**: local SQLite + remote REST API (automatic sync)
- **Thread-safe**: SQLite WAL mode — 10+ concurrent writers, zero conflicts
- **Deduplication**: SHA256 hash prevents duplicate entries
- **Compression**: zlib level 6 on local storage (3-5x ratio)
- **Backward compatible**: reads both encrypted and plaintext records
- **Zero core dependencies**: pure Python stdlib for local engine
- **18 tests**: including concurrency stress test and E2E round-trip

---

## Quick Start

### 1. Clone and install locally

```bash
git clone https://github.com/PauloFox0105/fox-memory.git
cd fox-memory

# Copy engine to shared location
mkdir -p ~/.claude-shared-memory
cp memory_bridge.py ~/.claude-shared-memory/
```

### 2. Generate encryption key (optional but recommended)

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" \
  > ~/.claude-shared-memory/.master_key
chmod 600 ~/.claude-shared-memory/.master_key
```

### 3. Use in Claude Code

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude-shared-memory"))
from memory_bridge import Memory

mem = Memory(session_id="cc-01")

# Save
mem.save("deploy", "my-app", {"status": "live", "commit": "abc123"})

# Search
mem.load("my-app")
mem.load("", categoria="deploy")

# Recent
mem.recent(limit=10)
mem.recent(limit=5, session_id="cc-02")

# Info
mem.sessions()
mem.stats()
```

---

## Remote API (Docker)

Deploy the REST API for remote access and Claude.ai integration.

### Setup

```bash
cd fox-memory

# Generate API key
export FOXMEMORY_API_KEY=$(python3 -c "import secrets; print('foxmem_' + secrets.token_hex(32))")

# Generate decrypt key (same as your .master_key, for server-side decryption)
export FOXMEMORY_DECRYPT_KEY=$(cat ~/.claude-shared-memory/.master_key)

# Create .env
cat > .env << EOF
FOXMEMORY_API_KEY=$FOXMEMORY_API_KEY
FOXMEMORY_DECRYPT_KEY=$FOXMEMORY_DECRYPT_KEY
EOF

# Build and run
docker compose up -d --build

# Verify
curl -H "X-Api-Key: $FOXMEMORY_API_KEY" http://localhost:18820/health
```

### Enable remote sync in memory_bridge

Set environment variables for your CC instances:

```bash
export FOXMEMORY_API_URL=https://your-domain.com  # or http://your-ip:18820
export FOXMEMORY_API_KEY=your_api_key_here
```

Every `mem.save()` will now write locally AND push encrypted data to the remote API.

---

## API Endpoints

All endpoints require `X-Api-Key` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server status |
| `GET` | `/memory/recent?limit=10` | Last N memories |
| `GET` | `/memory/search?q=text` | Search by text |
| `POST` | `/memory/save` | Save memory |
| `GET` | `/memory/sessions` | List sessions |
| `GET` | `/memory/stats` | Database stats |
| `DELETE` | `/memory/{id}` | Delete by ID |

### E2E Decryption

Add `X-Decrypt-Key` header to decrypt data on read:

```bash
# Without decrypt key → encrypted blobs
curl -H "X-Api-Key: $KEY" "$URL/memory/recent"
# {"dados": {"_e2e": "E2E:Zg6j..."}}

# With decrypt key → plaintext data
curl -H "X-Api-Key: $KEY" -H "X-Decrypt-Key: $DECRYPT_KEY" "$URL/memory/recent"
# {"dados": {"status": "live", "commit": "abc123"}}
```

### Save Request

```json
{
  "session_id": "cc-01",
  "categoria": "deploy",
  "contexto": "my-app",
  "dados": {"status": "live"}
}
```

### Authentication

- `X-Api-Key: your_key`
- `Authorization: Bearer your_key`

---

## Claude.ai MCP Setup

1. Deploy the API with HTTPS on a public domain
2. Go to **Claude.ai > Settings > MCP Servers > Add**
3. Configure:
   - **URL**: `https://your-domain.com`
   - **X-Api-Key**: your API key
   - **X-Decrypt-Key**: your master key (for reading decrypted data)

---

## Security

### 6 layers of protection

| Layer | Protection |
|-------|-----------|
| **E2E Encryption** | AES-256-GCM — server stores only ciphertext |
| **API Key** | 256-bit key required for all endpoints |
| **HTTPS** | TLS encryption in transit |
| **Rate Limiting** | nginx: 10 req/s per IP |
| **Fail2ban** | Auto-ban after 5 failed auth attempts |
| **Path Blocking** | Common attack paths return 444 |

### Key management

- **`.master_key`**: 256-bit AES key, lives ONLY on your local machine
- **`.env`**: API key + decrypt key, lives ONLY on the server
- **`.gitignore`**: excludes `.env`, `.master_key`, `*.db`
- Never commit secrets — generate fresh keys per deployment

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FOXMEMORY_API_URL` | Remote API URL for sync | _(empty = no sync)_ |
| `FOXMEMORY_API_KEY` | API authentication key | _(required for API)_ |
| `FOXMEMORY_DECRYPT_KEY` | Master key for server-side decrypt | _(empty = no decrypt)_ |
| `FOXMEMORY_REMOTE_SYNC` | Enable remote sync (`1`/`0`) | `1` |
| `FOXMEMORY_E2E` | Enable E2E encryption (`1`/`0`) | `1` |

---

## Tests

```bash
# Local tests (16 tests)
python3 tests.py

# With API tests (18 tests)
FOXMEMORY_API_URL=http://localhost:18820 FOXMEMORY_API_KEY=your_key python3 tests.py
```

---

## Files

```
fox-memory/
  memory_bridge.py    # Core engine (v3.0 — dual-write + E2E)
  api.py              # REST API (v2.0 — E2E decrypt support)
  tests.py            # Test suite (18 tests)
  Dockerfile          # Container image (Python 3.11 + cryptography)
  docker-compose.yml  # Docker deployment (env_file based)
  .env.example        # Environment template
  .gitignore          # Excludes .env, .master_key, *.db
  LICENSE             # MIT
```

---

## Categories

| Category | When to use |
|----------|-------------|
| `deploy` | After deploying an app or service |
| `dns` | After DNS record changes |
| `build` | Build results (pass/fail) |
| `test` | Test suite results |
| `api` | API configurations |
| `error` | Errors other instances should know about |
| `config` | Infrastructure changes |

---

## Contributing

1. Fork the repo
2. Create your branch: `git checkout -b feature/my-feature`
3. Run `python3 tests.py` — all tests must pass
4. Push and open a Pull Request

## License

MIT

---

<div align="center">

**Built with 🦊 by [Central Fox](https://centralfox.online)**

[Report Bug](https://github.com/PauloFox0105/fox-memory/issues) · [Request Feature](https://github.com/PauloFox0105/fox-memory/issues)

</div>
