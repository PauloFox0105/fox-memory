"""FoxMemory MCP Server v3 — OAuth + PKCE for Claude.ai."""

import os
import json
import time
import secrets
import urllib.request
import urllib.error
from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.server.transport_security import TransportSecuritySettings

API_URL = os.environ.get("FOXMEMORY_API_URL", "http://localhost:18820")
API_KEY = os.environ.get("FOXMEMORY_API_KEY", "")
DECRYPT_KEY = os.environ.get("FOXMEMORY_DECRYPT_KEY", "")
MCP_URL = os.environ.get("MCP_PUBLIC_URL", "http://localhost:18821")


@dataclass
class AuthCode:
    """Stored authorization code with metadata."""
    client_id: str
    redirect_uri: str
    code_challenge: str
    redirect_uri_provided_explicitly: bool
    scopes: list
    expires_at: float = 0.0

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = time.time() + 600  # 10 min


@dataclass
class RefreshTokenData:
    """Stored refresh token."""
    client_id: str
    scopes: list
    expires_at: float = 0.0

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = time.time() + 86400 * 365


@dataclass
class AccessTokenData:
    """Stored access token."""
    client_id: str
    scopes: list
    expires_at: float = 0.0
    token: str = ""

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = time.time() + 86400 * 365


@dataclass
class FoxMemoryOAuthProvider:
    """OAuth provider for FoxMemory MCP — supports PKCE public clients."""

    clients: dict = field(default_factory=dict)
    auth_codes: dict = field(default_factory=dict)
    access_tokens: dict = field(default_factory=dict)
    refresh_tokens: dict = field(default_factory=dict)

    async def get_client(self, client_id: str):
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params):
        code = secrets.token_hex(32)
        self.auth_codes[code] = AuthCode(
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri) if params.redirect_uri else "",
            code_challenge=params.code_challenge,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
        )
        # Return full redirect URL — MCP SDK uses this as Location header
        redirect = str(params.redirect_uri)
        url = f"{redirect}?code={code}"
        if params.state:
            url += f"&state={params.state}"
        return url

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        ac = self.auth_codes.get(authorization_code)
        if not ac or ac.client_id != client.client_id:
            return None
        return ac

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code):
        # authorization_code here is the AuthCode object returned by load_authorization_code
        code_key = None
        for k, v in self.auth_codes.items():
            if v is authorization_code:
                code_key = k
                break
        if code_key:
            del self.auth_codes[code_key]

        access_token = secrets.token_hex(32)
        refresh_token = secrets.token_hex(32)

        self.access_tokens[access_token] = AccessTokenData(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            token=access_token,
        )
        self.refresh_tokens[refresh_token] = RefreshTokenData(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=86400 * 365,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) or None,
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        rt = self.refresh_tokens.get(refresh_token)
        if not rt or rt.client_id != client.client_id:
            return None
        return rt

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token_data, scopes=None):
        access_token = secrets.token_hex(32)
        new_refresh = secrets.token_hex(32)

        use_scopes = scopes or refresh_token_data.scopes

        self.access_tokens[access_token] = AccessTokenData(
            client_id=client.client_id,
            scopes=use_scopes,
            token=access_token,
        )
        self.refresh_tokens[new_refresh] = RefreshTokenData(
            client_id=client.client_id,
            scopes=use_scopes,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=86400 * 365,
            refresh_token=new_refresh,
        )

    async def load_access_token(self, token: str):
        at = self.access_tokens.get(token)
        if not at:
            return None
        if at.expires_at < time.time():
            del self.access_tokens[token]
            return None
        return at

    async def revoke_token(self, token, token_type_hint=None):
        self.access_tokens.pop(token, None)
        self.refresh_tokens.pop(token, None)


oauth_provider = FoxMemoryOAuthProvider()

mcp = FastMCP(
    "FoxMemory",
    instructions="Shared memory for Fox's 10 Claude Code instances. Tools: memory_search, memory_recent, memory_save, memory_sessions, memory_stats.",
    host="0.0.0.0",
    port=int(os.environ.get("MCP_PORT", "18821")),
    auth_server_provider=oauth_provider,
    auth=AuthSettings(
        issuer_url=MCP_URL,
        resource_server_url=MCP_URL,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["memory:read", "memory:write"],
            default_scopes=["memory:read", "memory:write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ],
    ),
)


# ── API Bridge ───────────────────────────────────────────

def _api(method, endpoint, body=None):
    url = f"{API_URL}{endpoint}"
    headers = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}
    if DECRYPT_KEY:
        headers["X-Decrypt-Key"] = DECRYPT_KEY
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ── Tools ────────────────────────────────────────────────

@mcp.tool()
def memory_search(query: str, categoria: str = "", limit: int = 20) -> str:
    """Search memories by text. Args: query, categoria (optional), limit."""
    params = f"q={query}&limit={limit}"
    if categoria:
        params += f"&categoria={categoria}"
    result = _api("GET", f"/memory/search?{params}")
    if "error" in result:
        return json.dumps(result)
    out = []
    for r in result.get("results", []):
        out.append(f"[{r['session_id']}] {r['categoria']}/{r['contexto']}")
        out.append(f"  {json.dumps(r['dados'], ensure_ascii=False)[:200]}")
    return f"{result.get('count', 0)} results:\n" + "\n".join(out) if out else "No results."


@mcp.tool()
def memory_recent(limit: int = 10, session_id: str = "") -> str:
    """Get most recent memories. Args: limit, session_id (optional, e.g. 'cc-1')."""
    params = f"limit={limit}"
    if session_id:
        params += f"&session_id={session_id}"
    result = _api("GET", f"/memory/recent?{params}")
    if "error" in result:
        return json.dumps(result)
    out = []
    for r in result.get("results", []):
        out.append(f"[{r['session_id']}] {r['categoria']}/{r['contexto']}")
        out.append(f"  {json.dumps(r['dados'], ensure_ascii=False)[:200]}")
    return f"{len(result.get('results', []))} memories:\n" + "\n".join(out) if out else "No memories."


@mcp.tool()
def memory_save(session_id: str, categoria: str, contexto: str, dados: str) -> str:
    """Save a memory. Args: session_id (e.g. 'claude-web'), categoria, contexto, dados (JSON)."""
    try:
        d = json.loads(dados) if isinstance(dados, str) else dados
    except json.JSONDecodeError:
        d = {"raw": dados}
    result = _api("POST", "/memory/save", {
        "session_id": session_id,
        "categoria": categoria,
        "contexto": contexto,
        "dados": d,
    })
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Saved: {result.get('message', 'OK')} (ID={result.get('id', '?')})"


@mcp.tool()
def memory_sessions() -> str:
    """List all active CC sessions with memory counts."""
    result = _api("GET", "/memory/sessions")
    if "error" in result:
        return json.dumps(result)
    out = [f"  {s['session_id']}: {s['count']} memories" for s in result.get("sessions", [])]
    return "\n".join(out) if out else "No sessions."


@mcp.tool()
def memory_stats() -> str:
    """Get database statistics."""
    result = _api("GET", "/memory/stats")
    if "error" in result:
        return json.dumps(result)
    cats = ", ".join(f"{k}={v}" for k, v in result.get("categorias", {}).items())
    return f"Total: {result.get('total_memories', 0)} | Size: {result.get('db_size_kb', 0)}KB | Sessions: {result.get('sessions', 0)} | Categories: {cats}"


@mcp.tool()
def memory_delete(memory_id: int) -> str:
    """Delete a specific memory by ID."""
    result = _api("DELETE", f"/memory/{memory_id}")
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Deleted memory ID={memory_id}"


@mcp.tool()
def foxshield_project_status() -> str:
    """Get FoxShield project status — which CCs finished, tests, deploy state."""
    result = _api("GET", "/memory/search?q=foxshield&limit=50")
    if "error" in result:
        return json.dumps(result)
    done = []
    started = []
    for r in result.get("results", []):
        ctx = r.get("contexto", "")
        dados = r.get("dados", {})
        status = dados.get("status", "")
        if "done" in ctx:
            notas = dados.get("notas", "")[:80]
            task = dados.get("task", "")
            testes = dados.get("testes", "")
            done.append(f"  {ctx}: {task or status} {f'| tests={testes}' if testes else ''} {f'| {notas}' if notas else ''}")
        elif "start" in ctx:
            started.append(f"  {ctx}: {dados.get('task', '')} (started)")
    out = f"=== DONE ({len(done)}) ===\n" + "\n".join(done) if done else "No completed tasks"
    if started:
        out += f"\n\n=== IN PROGRESS ({len(started)}) ===\n" + "\n".join(started)
    return out


@mcp.tool()
def vps_health() -> str:
    """Check VPS Contabo health — Docker containers, services, disk, memory."""
    import subprocess
    checks = {}
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True, timeout=10)
        containers = []
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                containers.append(line.strip())
        checks["containers"] = containers
    except Exception as e:
        checks["containers_error"] = str(e)
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")
        if len(lines) > 1:
            checks["disk"] = lines[1].split()
    except Exception:
        pass
    try:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")
        if len(lines) > 1:
            checks["memory"] = lines[1].split()
    except Exception:
        pass
    try:
        r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
        checks["uptime"] = r.stdout.strip()
    except Exception:
        pass
    out = []
    out.append(f"Uptime: {checks.get('uptime', '?')}")
    if "memory" in checks:
        m = checks["memory"]
        out.append(f"RAM: {m[2]} used / {m[1]} total")
    if "disk" in checks:
        d = checks["disk"]
        out.append(f"Disk: {d[2]} used / {d[1]} total ({d[4]} full)")
    out.append(f"\nContainers ({len(checks.get('containers', []))}):")
    for c in checks.get("containers", []):
        out.append(f"  {c}")
    return "\n".join(out)


@mcp.tool()
def cc_activity(limit: int = 30) -> str:
    """Summary of what each CC did — grouped by session ID."""
    result = _api("GET", f"/memory/recent?limit={limit}")
    if "error" in result:
        return json.dumps(result)
    grouped = {}
    for r in result.get("results", []):
        sid = r.get("session_id", "unknown")
        if sid not in grouped:
            grouped[sid] = []
        dados = r.get("dados", {})
        ctx = r.get("contexto", "")
        status = dados.get("status", "")
        task = dados.get("task", "")
        notas = dados.get("notas", "")[:60]
        grouped[sid].append(f"    {ctx}: {status} {task} {notas}".rstrip())
    out = []
    for sid, items in grouped.items():
        out.append(f"  [{sid}] ({len(items)} records)")
        for item in items[:5]:
            out.append(item)
        if len(items) > 5:
            out.append(f"    ... +{len(items)-5} more")
    return f"{len(grouped)} sessions:\n" + "\n".join(out) if out else "No activity."


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
