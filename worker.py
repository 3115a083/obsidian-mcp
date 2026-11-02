"""Internal read-only vault worker. No GitHub credentials or other vault mounts."""
import hmac
import json
import os
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool
from vault import Vault


def create_worker(root, token):
    if len(token) < 40:
        raise ValueError("A strong internal worker credential is required")
    vault = Vault(root)

    async def dispatch(request):
        candidate = request.headers.get("authorization", "")
        if not hmac.compare_digest(candidate.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return JSONResponse({"error": "request too large"}, status_code=413)
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected object")
            operation = request.path_params["operation"]
            functions = {"list": vault.list_notes, "read": vault.read_note, "search": vault.search_notes}
            if operation not in functions:
                return JSONResponse({"error": "unknown operation"}, status_code=404)
            result = await run_in_threadpool(functions[operation], **data)
            return JSONResponse(result)
        except (ValueError, TypeError, OSError, UnicodeError):
            return JSONResponse({"error": "Invalid request or note unavailable"}, status_code=400)

    return Starlette(routes=[Route("/{operation}", dispatch, methods=["POST"])])


if os.environ.get("WORKER_TOKEN"):
    app = create_worker(os.environ.get("VAULT_ROOT", "/vault"), os.environ["WORKER_TOKEN"])
