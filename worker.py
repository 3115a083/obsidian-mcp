"""Internal scoped vault worker. No GitHub credentials or other vault mounts."""
import hmac
import json
import os
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool
from vault import NoteConflict, Vault


def create_worker(root, token, writable_paths=None):
    if len(token) < 40:
        raise ValueError("A strong internal worker credential is required")
    vault = Vault(root, writable_paths)

    async def dispatch(request):
        candidate = request.headers.get("authorization", "")
        if not hmac.compare_digest(candidate.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8 * 1024 * 1024:
                return JSONResponse({"error": "request too large"}, status_code=413)
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected object")
            operation = request.path_params["operation"]
            functions = {"list": vault.list_notes, "read": vault.read_note, "search": vault.search_notes}
            functions.update({name: getattr(vault, name) for name in
                              ('create_note', 'update_note', 'patch_note', 'move_note',
                               'list_note_versions', 'restore_note')})
            if operation not in functions:
                return JSONResponse({"error": "unknown operation"}, status_code=404)
            result = await run_in_threadpool(functions[operation], **data)
            return JSONResponse(result)
        except NoteConflict as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        except PermissionError:
            return JSONResponse({"error": "Write path not enabled or filesystem permission denied"}, status_code=403)
        except (ValueError, TypeError, OSError, UnicodeError):
            return JSONResponse({"error": "Invalid request or note unavailable"}, status_code=400)

    return Starlette(routes=[Route("/{operation}", dispatch, methods=["POST"])])


if os.environ.get("WORKER_TOKEN"):
    app = create_worker(os.environ.get("VAULT_ROOT", "/vault"), os.environ["WORKER_TOKEN"],
                        json.loads(os.environ.get('VAULT_WRITE_PATHS', '[]')))
