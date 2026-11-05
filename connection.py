"""Separate HTTP ingress for direct OAuth clients, never for administration."""
import asyncio
import hmac
import os
from pathlib import Path
import time

from starlette.responses import JSONResponse


class IngressFence:
    """Nginx overwrites this routing marker on each of its two listeners."""
    def __init__(self, app, *, entry):
        self.app, self.entry = app, entry.encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            values = [v for k, v in scope.get('headers', []) if k.lower() == b'x-obsidian-connection']
            # Headerless in-process/legacy access remains compatible. The
            # public direct listener must always supply its own exact marker.
            if values != [self.entry] and not (self.entry == b'legacy' and not values):
                return await JSONResponse({'error': 'route_not_available'}, status_code=404)(scope, receive, send)
        await self.app(scope, receive, send)


class DirectAccessGuard:
    """Origin authentication and bounded anonymous OAuth/DCR traffic.

    Uses instance-wide limits rather than trusting client Forwarded/IP headers.
    No secrets or request bodies are logged. Only the direct OAuth store counts
    toward the storage budget; existing browser/legacy state is untouched.
    """
    def __init__(self, app, *, secret, state_dir, max_state_bytes=32 * 1024 * 1024):
        if len(secret) < 43:
            raise ValueError('MCP_ORIGIN_SECRET must be at least 43 characters')
        self.app, self.secret = app, secret.encode()
        self.state_dir = Path(state_dir)
        self.max_state_bytes = max_state_bytes
        self.active = 0
        self.buckets = {}

    def allowed(self, key, burst, rate):
        now = time.monotonic()
        tokens, previous = self.buckets.get(key, (float(burst), now))
        tokens = min(burst, tokens + (now - previous) * rate)
        self.buckets[key] = (tokens - 1 if tokens >= 1 else tokens, now)
        return tokens >= 1

    def storage_has_room(self):
        pending, entries, size = [self.state_dir], 0, 0
        try:
            while pending:
                path = pending.pop()
                if not path.exists():
                    continue
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        entries += 1
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                        if entries > 4096 or size > self.max_state_bytes:
                            return False
        except OSError:
            return False
        return True

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if path == '/healthz' and scope.get('method') == 'GET':
            return await self.app(scope, receive, send)
        headers = scope.get('headers', [])
        values = [v for k, v in headers if k.lower() == b'x-pangolin-origin']
        if len(values) != 1 or not hmac.compare_digest(values[0], self.secret):
            return await JSONResponse({'error': 'origin_not_allowed'}, status_code=403)(scope, receive, send)

        async def reject(status, code):
            return await JSONResponse({'error': code}, status_code=status)(scope, receive, send)

        if not self.allowed('all', 120, 4):
            return await reject(429, 'request_rate_limited')
        if path == '/register' and not self.allowed('register', 10, 1 / 30):
            return await reject(429, 'registration_rate_limited')
        if self.active >= 8:
            return await reject(503, 'busy')
        if path != '/mcp' and not self.storage_has_room():
            return await reject(503, 'oauth_storage_budget_exceeded')
        maximum = 64 * 1024 if path == '/mcp' else 16 * 1024
        lengths = [v for k, v in headers if k.lower() == b'content-length']
        try:
            if len(lengths) > 1 or lengths and int(lengths[0]) < 0:
                return await reject(400, 'invalid_content_length')
            if lengths and int(lengths[0]) > maximum:
                return await reject(413, 'request_too_large')
        except ValueError:
            return await reject(400, 'invalid_content_length')
        self.active += 1
        try:
            chunks, size = [], 0
            try:
                async with asyncio.timeout(20):
                    while True:
                        event = await receive()
                        if event['type'] == 'http.disconnect':
                            return
                        chunk = event.get('body', b'')
                        size += len(chunk)
                        if size > maximum:
                            return await reject(413, 'request_too_large')
                        chunks.append(chunk)
                        if not event.get('more_body', False):
                            break
            except TimeoutError:
                return await reject(408, 'body_timeout')
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            self.active -= 1
