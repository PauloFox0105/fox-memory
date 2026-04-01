# FoxMemory v3.0

Encrypted shared memory for multiple Claude Code instances + Claude.ai.

**10 CCs in parallel, one shared brain, E2E encrypted, zero context lost.**

## Architecture

```
CC1  ──┐
CC2  ──┤
CC3  ──┤── memory_bridge.py ──┬── SQLite local (plaintext, fast)
...    ┤   (dual-write)       └── REST API (AES-256-GCM encrypted)
CC10 ──┘                               ↑
                                   HTTPS + TLS
                                        │
                              ┌─────────┴─────────┐
                              │  MCP Server (OAuth) │
                              └─────────┬─────────┘
                                        │
Claude.ai (web) ─── MCP Protocol ──────┘
```

## Features

- **E2E Encryption** — AES-256-GCM, data encrypted before leaving your machine
- **Dual-write** — local SQLite + remote REST API (automatic sync)
- **MCP Server** — Claude.ai connects via OAuth + PKCE (9 tools)
- **Thread-safe** — SQLite WAL mode, 10+ concurrent writers
- **Deduplication** — SHA256 hash prevents duplicates
- **Compression** — zlib on local storage (3-5x ratio)
- **18 tests** — including concurrency stress and E2E round-trip

---

## Quick Start

### 1. Install locally

```bash
git clone https://github.com/PauloFox0105/fox-memory.git
cd fox-memory
mkdir -p ~/.claude-shared-memory
cp memory_bridge.py ~/.claude-shared-memory/
```

### 2. Generate encryption key

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
mem.save("deploy", "my-app", {"status": "live", "commit": "abc123"})
mem.load("my-app")
mem.recent(limit=10)
mem.sessions()
mem.stats()
```

### 4. Enable remote sync

```bash
export FOXMEMORY_API_URL=https://your-server.com
export FOXMEMORY_API_KEY=your_api_key
```

Every `mem.save()` now writes locally AND pushes encrypted data to the remote API.

---

## Deploy REST API (Docker)

```bash
cd fox-memory
cp .env.example .env
# Edit .env with your API key and decrypt key

docker compose up -d --build
# REST API: http://localhost:18820
# MCP Server: http://localhost:18821
```

### API Endpoints

All require `X-Api-Key` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server status |
| `GET` | `/memory/recent?limit=10` | Last N memories |
| `GET` | `/memory/search?q=text` | Search by text |
| `POST` | `/memory/save` | Save memory |
| `GET` | `/memory/sessions` | List sessions |
| `GET` | `/memory/stats` | Database stats |
| `DELETE` | `/memory/{id}` | Delete by ID |

### E2E Decrypt on read

```bash
# Without X-Decrypt-Key → encrypted blobs
curl -H "X-Api-Key: $KEY" "$URL/memory/recent"

# With X-Decrypt-Key → plaintext
curl -H "X-Api-Key: $KEY" -H "X-Decrypt-Key: $MASTER_KEY" "$URL/memory/recent"
```

---

## Connect Claude.ai (MCP)

The MCP server implements OAuth 2.0 + PKCE for secure Claude.ai integration.

### 1. Deploy with HTTPS

The MCP server needs a public HTTPS domain. Set up nginx reverse proxy:

```nginx
server {
    listen 443 ssl;
    server_name mcp.your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:18821;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

### 2. Configure environment

```bash
# In .env
MCP_PUBLIC_URL=https://mcp.your-domain.com
FOXMEMORY_API_URL=http://fox-memory:18810   # internal Docker network
FOXMEMORY_API_KEY=your_api_key
FOXMEMORY_DECRYPT_KEY=your_master_key       # for server-side decrypt
```

### 3. Add allowed hosts

Edit `mcp_server.py` and add your domain to `allowed_hosts` in `TransportSecuritySettings`.

### 4. Connect in Claude.ai

1. **Claude.ai → Settings → Integrations → Add**
2. **URL:** `https://mcp.your-domain.com/mcp`
3. Leave Client ID/Secret blank (dynamic registration)
4. Authorize in popup

### Available MCP Tools (9)

| Tool | Description |
|------|-------------|
| `memory_search` | Search memories by text/category |
| `memory_recent` | Get last N memories |
| `memory_save` | Save a memory |
| `memory_delete` | Delete memory by ID |
| `memory_sessions` | List active CC sessions |
| `memory_stats` | Database statistics |
| `foxshield_project_status` | Project status across CCs |
| `vps_health` | Server health (containers, RAM, disk) |
| `cc_activity` | Activity summary grouped by CC |

---

## Security

| Layer | Protection |
|-------|-----------|
| **E2E Encryption** | AES-256-GCM — server stores only ciphertext |
| **API Key** | 256-bit key for all REST endpoints |
| **OAuth + PKCE** | MCP server uses OAuth 2.0 with PKCE for Claude.ai |
| **HTTPS** | TLS encryption in transit |
| **Rate Limiting** | nginx: 10 req/s per IP |
| **Fail2ban** | Auto-ban after 5 failed auth attempts |

### Key files (never commit these)

- `.master_key` — AES-256 encryption key (local only)
- `.env` — API keys and secrets (server only)

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FOXMEMORY_API_URL` | Remote API URL for sync | _(empty = no sync)_ |
| `FOXMEMORY_API_KEY` | API authentication key | _(required)_ |
| `FOXMEMORY_DECRYPT_KEY` | Master key for server-side decrypt | _(empty)_ |
| `FOXMEMORY_REMOTE_SYNC` | Enable remote sync | `1` |
| `FOXMEMORY_E2E` | Enable E2E encryption | `1` |
| `MCP_PUBLIC_URL` | Public URL for OAuth issuer | `http://localhost:18821` |
| `MCP_PORT` | MCP server port | `18821` |

---

## Tests

```bash
# Local (16 tests)
python3 tests.py

# With API (18 tests)
FOXMEMORY_API_URL=http://localhost:18820 FOXMEMORY_API_KEY=your_key python3 tests.py
```

---

## Files

```
fox-memory/
  memory_bridge.py    # Core engine (v3 — dual-write + E2E)
  api.py              # REST API (v2 — E2E decrypt support)
  mcp_server.py       # MCP server (v3 — OAuth + PKCE + 9 tools)
  run_mcp.py          # MCP runner with OAuth metadata patch
  tests.py            # 18 tests
  Dockerfile          # REST API container
  Dockerfile.mcp      # MCP server container
  docker-compose.yml  # Both services
  .env.example        # Environment template
  LICENSE             # MIT
```

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
