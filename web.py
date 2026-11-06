"""One central GitHub browser login and CSRF-protected configuration forms."""
import hmac
import secrets
import time
from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from deployment import write_override
from state import Conflict
from ui import dashboard, document, esc


def web_routes(settings, state, oauth_transport=None):
    oauth = OAuth()
    kwargs = {"scope": "", "code_challenge_method": "S256", "timeout": 10,
              "follow_redirects": False, "trust_env": False}
    if oauth_transport is not None:
        kwargs["transport"] = oauth_transport
    github = oauth.register("github", client_id=settings.github_client_id,
        client_secret=settings.github_client_secret, authorize_url="https://github.com/login/oauth/authorize",
        access_token_url="https://github.com/login/oauth/access_token", token_endpoint_auth_method="client_secret_post", client_kwargs=kwargs)  # nosec B106 # OAuth method identifier and public token endpoint, not a password.

    def owner(request):
        return (request.session.get("owner") == settings.github_owner_id and
                request.session.get("expires", 0) > time.time())

    def csrf(request):
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(32)
        return request.session["csrf"]

    def form_allowed(request, form):
        incoming = request.headers.get("origin")
        expected = csrf(request)
        return (owner(request) and (incoming is None or incoming == settings.public_url) and
                hmac.compare_digest(str(form.get("csrf", "")).encode(), expected.encode()))

    def login_required():
        return RedirectResponse("/login", status_code=303)

    async def login(request):
        if owner(request):
            return RedirectResponse("/admin/", status_code=303)
        return document('<div class="tag">Obsidian MCP</div><h1>Mit GitHub anmelden</h1><p>Eine Anmeldung für die gesamte Verwaltung. Nur das freigegebene GitHub-Konto erhält Zugriff.</p><a class="button" href="/auth/login">Mit GitHub fortfahren</a>')

    async def start_login(request):
        return await github.authorize_redirect(request, settings.public_url + "/auth/callback")

    async def callback(request):
        try:
            token = await github.authorize_access_token(request)
            response = await github.get("https://api.github.com/user", token=token)
            response.raise_for_status()
            identity = str(response.json().get("id", ""))
        except (OAuthError, ValueError):
            return document('<h1>Anmeldung nicht abgeschlossen</h1><p>Der OAuth-Status ist ungültig oder abgelaufen. <a href="/login">Erneut anmelden</a>.</p>', status=400)
        except Exception:
            # No OAuth tokens, provider responses or query parameters in logs/HTML.
            return document('<h1>GitHub derzeit nicht erreichbar</h1><p>Bitte später erneut versuchen.</p>', status=502)
        request.session.clear()
        if identity != settings.github_owner_id:
            return document('<h1>Zugriff verweigert</h1><p>Dieses GitHub-Konto ist nicht freigegeben.</p>', status=403)
        request.session.update(owner=identity, expires=int(time.time()) + 3600, csrf=secrets.token_urlsafe(32))
        return RedirectResponse("/admin/", status_code=303)

    async def index(request):
        if not owner(request):
            return login_required()
        notice = "Gespeichert. Jetzt in Dockge neu einlesen und deployen." if request.query_params.get("saved") == "1" else ""
        return dashboard(settings, state, csrf(request), notice=notice)

    async def current_session(request):
        if not owner(request):
            return JSONResponse({"message": "Sitzung abgelaufen. In einem zweiten Tab erneut anmelden; deine Eingaben bleiben hier erhalten."}, status_code=401, headers={"Cache-Control": "no-store"})
        return JSONResponse({"csrf": csrf(request)}, headers={"Cache-Control": "no-store"})

    async def save(request):
        ajax = "application/json" in request.headers.get("accept", "")
        if not owner(request):
            return JSONResponse({"message": "Sitzung abgelaufen. In einem zweiten Tab erneut anmelden; deine Eingaben bleiben hier erhalten."}, status_code=401) if ajax else login_required()
        form = await request.form(max_fields=350)
        if not form_allowed(request, form):
            if ajax:
                return JSONResponse({"message": "Formularprüfung abgewiesen. Eingaben bleiben erhalten. In einem zweiten Tab erneut anmelden."}, status_code=403)
            return document('<h1>Anfrage abgewiesen</h1><p>Sitzung oder Formularprüfung ungültig. <a href="/admin/">Verwaltung neu öffnen</a>.</p>', status=403)
        fields = [form.getlist("vault_" + name) for name in ("name", "label", "directory")]
        write_fields = form.getlist("vault_write_paths")
        fields.append(write_fields if write_fields else ["" for _ in fields[0]])
        draft = [dict(zip(("name", "label", "directory", "write_paths"), items)) for items in zip(*fields)]
        try:
            if len({len(values) for values in fields}) != 1:
                raise ValueError("Ungültige Formularfelder")
            revision = int(form.get("revision", "-1"))
            config = state.prepare_vaults(draft, settings.vault_parent)
            state.save_config(config, revision,
                lambda data, rev: write_override(settings.override_file, data, state, rev))
        except (ValueError, OSError) as error:
            if ajax:
                return JSONResponse({"message": str(error)}, status_code=409 if isinstance(error, Conflict) else 400)
            return dashboard(settings, state, csrf(request), notice=str(error),
                status=409 if isinstance(error, Conflict) else 400,
                draft=draft, revision=form.get("revision", "-1"))
        if ajax:
            return JSONResponse({"revision": revision + 1, "message": "Gespeichert. Den Befehl unter „Gespeicherte Konfiguration anwenden“ im Stack-Verzeichnis ausführen oder in Dockge neu einlesen und deployen. Neue Client-Freigaben sind im aktuellen Stand im zweiten Tab verfügbar."})
        return RedirectResponse("/admin/?saved=1", status_code=303)

    async def issue_client(request):
        if not owner(request):
            return login_required()
        form = await request.form(max_fields=100)
        if not form_allowed(request, form):
            return document('<h1>Anfrage abgewiesen</h1>', status=403)
        draft = {"label": str(form.get("client_label", "")), "days": str(form.get("days", "")), "vault_ids": form.getlist("vault_id"), "write_vault_ids": form.getlist("write_vault_id")}
        try:
            raw, _ = state.issue_client(draft["label"], draft["vault_ids"], int(draft["days"]), draft["write_vault_ids"])
        except ValueError as error:
            return dashboard(settings, state, csrf(request), notice=str(error), status=400, client_draft=draft)
        return dashboard(settings, state, csrf(request), raw_token=raw, client_draft=draft)

    async def revoke(request):
        if not owner(request):
            return login_required()
        form = await request.form()
        if not form_allowed(request, form):
            return document('<h1>Anfrage abgewiesen</h1>', status=403)
        state.revoke_client(str(form.get("client_id", "")))
        return RedirectResponse("/admin/", status_code=303)

    async def logout(request):
        form = await request.form()
        if not form_allowed(request, form):
            return document('<h1>Anfrage abgewiesen</h1>', status=403)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    async def deployment(request):
        if not owner(request):
            return login_required()
        # This file contains internal worker credentials. It is owner-only and no-store.
        return document('<a href="/admin/">Zurück</a><h1>Lokale Compose-Ergänzung</h1><p>Enthält interne Zugangsdaten. Nicht veröffentlichen.</p><pre><code>' + esc(settings.override_file.read_text()) + '</code></pre>')

    return [Route("/", index), Route("/login", login), Route("/admin/login", login),
        Route("/auth/login", start_login), Route("/auth/callback", callback),
        Route("/admin", index), Route("/admin/", index), Route("/admin/session", current_session), Route("/admin/save", save, methods=["POST"]),
        Route("/admin/clients", issue_client, methods=["POST"]), Route("/admin/revoke", revoke, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]), Route("/admin/deployment", deployment)], github
