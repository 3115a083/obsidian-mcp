from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import httpx2
from settings import Settings


def settings_for(root, public_url="https://obsidian.test"):
    root = Path(root)
    override = root / "compose.override.yaml"
    override.write_text("services: {}\n")
    return Settings(public_url, "synthetic-client-id", "synthetic-client-secret", "12345",
                    root / "data", override, Path("/srv/obsidian/vaults"))


def github_transport(owner=12345, capture=None):
    def reply(request):
        if request.url.host == "github.com" and request.url.path == "/login/oauth/access_token":
            fields = parse_qs(request.content.decode())
            if capture is not None:
                capture.append(fields)
            if fields.get("grant_type") != ["authorization_code"] or not fields.get("code_verifier"):
                return httpx2.Response(400, json={"error": "invalid_request"})
            return httpx2.Response(200, json={"access_token": "synthetic-oauth-access", "token_type": "Bearer", "scope": ""})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx2.Response(200, json={"id": owner, "login": "synthetic-owner"})
        return httpx2.Response(404)
    return httpx2.MockTransport(reply)


def login(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return client.get("/auth/callback", params={"state": query["state"][0], "code": "synthetic-code"}, follow_redirects=True)
