import os, json
os.environ.setdefault('FOXMEMORY_API_URL', 'http://localhost:18820')
from mcp_server import mcp
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

app = mcp.streamable_http_app()

class PatchOAuthMetadata(BaseHTTPMiddleware):
    """Add 'none' to token_endpoint_auth_methods_supported for public clients (Claude.ai)."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path == '/.well-known/oauth-authorization-server':
            body = b''
            async for chunk in response.body_iterator:
                body += chunk if isinstance(chunk, bytes) else chunk.encode()
            try:
                data = json.loads(body)
                methods = data.get('token_endpoint_auth_methods_supported', [])
                if 'none' not in methods:
                    methods.append('none')
                    data['token_endpoint_auth_methods_supported'] = methods
                rev_methods = data.get('revocation_endpoint_auth_methods_supported', [])
                if 'none' not in rev_methods:
                    rev_methods.append('none')
                    data['revocation_endpoint_auth_methods_supported'] = rev_methods
                new_body = json.dumps(data).encode()
                return Response(content=new_body, status_code=200, media_type='application/json')
            except Exception:
                return Response(content=body, status_code=response.status_code, media_type='application/json')
        return response

app.add_middleware(PatchOAuthMetadata)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('MCP_PORT', '18821')))
