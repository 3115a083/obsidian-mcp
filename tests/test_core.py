import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx2
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider
from starlette.testclient import TestClient

from app import create_app
from auth import OwnerGitHubProvider
from bridge import create_bridge
from deployment import compose_override, write_override
from settings import Settings
from state import Conflict, State
from vault import Vault
from worker import create_worker
from tests.support import github_transport, login, settings_for


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = settings_for(self.root)
        self.store = State(self.settings.data_dir)

    def save_vaults(self, items):
        revision, _ = self.store.config()
        config = self.store.prepare_vaults(items, self.settings.vault_parent)
        self.store.save_config(config, revision, lambda data, rev: write_override(self.settings.override_file, data, self.store, rev))
        return config["vaults"]


class FileBoundaryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.vault_root = self.root / "vault"
        self.vault_root.mkdir()
        (self.vault_root / "Session.md").write_text("# Session\nStrahd arrived.\nPreparation only.\n")
        (self.vault_root / ".obsidian").mkdir()
        (self.vault_root / ".obsidian" / "secret.md").write_text("private-marker")
        (self.root / "outside.md").write_text("private-marker")
        (self.vault_root / "link.md").symlink_to(self.root / "outside.md")
        (self.vault_root / "directory-link").symlink_to(self.vault_root / ".obsidian", target_is_directory=True)
        self.vault = Vault(self.vault_root)

    def test_inventory_and_search_do_not_expose_hidden_or_linked_files(self):
        self.assertEqual(self.vault.list_notes()["paths"], ["Session.md"])
        self.assertEqual(self.vault.search_notes("private-marker")["matches"], [])
        self.assertEqual(self.vault.search_notes("STRAHD")["matches"][0]["line"], 2)

    def test_traversal_links_and_other_formats_rejected(self):
        for path in ("../outside.md", "/outside.md", ".obsidian/secret.md", "link.md", "directory-link/secret.md", "a\\b.md", "token.env", "a/../Session.md"):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.vault.read_note(path)

    def test_fifo_large_notes_and_large_lines_are_bounded(self):
        os.mkfifo(self.vault_root / "pipe.md")
        with self.assertRaises(ValueError):
            self.vault.read_note("pipe.md")
        (self.vault_root / "large.md").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.vault.read_note("large.md")
        (self.vault_root / "line.md").write_text("x" * 16001)
        with self.assertRaises(ValueError):
            self.vault.read_note("line.md")

    def test_pagination_and_worker_authentication(self):
        self.assertEqual(self.vault.read_note("Session.md", 2, 1)["next_line"], 3)
        with TestClient(create_worker(self.vault_root, "k" * 64)) as client:
            self.assertEqual(client.post("/read", json={"path": "Session.md"}).status_code, 401)
            response = client.post("/read", headers={"Authorization": "Bearer " + "k" * 64}, json={"path": "Session.md"})
            self.assertEqual(response.status_code, 200)
            response = client.post("/read", headers={"Authorization": "Bearer " + "k" * 64}, json={"path": "link.md"})
            self.assertEqual(response.status_code, 400)


class ConfigurationAndTokenTests(Fixture):
    def test_adding_vault_requires_only_data_and_read_only_mount(self):
        vaults = self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}])
        first_id = vaults[0]["id"]
        vaults = self.save_vaults([{"name": "llm", "label": "Updated label", "directory": "/srv/obsidian/vaults/LLMs"},
            {"name": "strahd", "label": "D&D", "directory": "/srv/obsidian/vaults/Strahd"}])
        self.assertEqual(first_id, vaults[0]["id"])
        deployment = json.loads(self.settings.override_file.read_text().split("\n", 1)[1])
        for service in deployment["services"].values():
            self.assertTrue(service["volumes"][0]["read_only"])
            self.assertFalse(service["volumes"][0]["bind"]["create_host_path"])
            self.assertNotIn("ports", service)
            self.assertNotIn("build", service)
            self.assertNotIn("GITHUB_CLIENT_SECRET", service["environment"])

    def test_literal_dollar_path_cannot_expand_compose_environment(self):
        raw = "/srv/obsidian/vaults/${OTHER_ROOT}/$campaign"
        vault = self.save_vaults([{"name": "llm", "label": "Literal path", "directory": raw}])[0]
        deployment = json.loads(self.settings.override_file.read_text().split("\n", 1)[1])
        self.assertEqual(vault["directory"], raw)
        self.assertEqual(deployment["services"]["vault-llm"]["volumes"][0]["source"],
                         "/srv/obsidian/vaults/$${OTHER_ROOT}/$$campaign")

    def test_invalid_names_duplicate_directories_and_outside_paths_rejected(self):
        for name, path in (("../escape", "/srv/obsidian/vaults/a"), ("UPPER", "/srv/obsidian/vaults/a"),
                           ("valid", "/etc"), ("valid", "/srv/obsidian/vaults"),
                           ("valid", "/srv/obsidian/vaults/a/../b")):
            with self.subTest(name=name, path=path), self.assertRaises(ValueError):
                self.store.prepare_vaults([{"name": name, "label": "Label", "directory": path}], self.settings.vault_parent)

    def test_stale_form_cannot_overwrite_new_config(self):
        self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}])
        with self.assertRaises(Conflict):
            self.store.save_config({"vaults": []}, 0, lambda *_: self.fail("A stale draft wrote deployment output"))
        self.assertEqual(self.store.config()[1]["vaults"][0]["name"], "llm")

    def test_capability_hash_revocation_and_expiry(self):
        vault = self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}])[0]
        raw, identity = self.store.issue_client("Test client", [vault["id"]], 1)
        self.assertNotIn(raw.encode(), self.store.db.read_bytes())
        self.assertEqual(self.store.verify_client(raw)["vault_ids"], [vault["id"]])
        with patch("state.time.time", return_value=time.time() + 86401):
            self.assertIsNone(self.store.verify_client(raw))
        self.store.revoke_client(identity)
        self.assertIsNone(self.store.verify_client(raw))

    def test_retargeted_or_recreated_vault_does_not_inherit_old_capability(self):
        original = self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}])[0]
        raw, _ = self.store.issue_client("Test", [original["id"]], 1)
        changed = self.save_vaults([{"name": "llm", "label": "Other", "directory": "/srv/obsidian/vaults/Other"}])[0]
        self.assertNotIn(changed["id"], self.store.verify_client(raw)["vault_ids"])
        self.save_vaults([])
        recreated = self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}])[0]
        self.assertNotEqual(original["id"], recreated["id"])


class BrowserAndOAuthTests(Fixture):
    def client(self, owner=12345, capture=None):
        app = create_app(self.settings, state=self.store, oauth_transport=github_transport(owner, capture))
        return TestClient(app, base_url=self.settings.public_url)

    def token(self, response):
        return re.search(r'name="csrf" value="([^\"]+)"', response.text).group(1)

    def test_central_github_login_uses_pkce_and_one_config(self):
        capture = []
        with self.client(capture=capture) as client:
            self.assertEqual(client.get("/admin/", follow_redirects=False).status_code, 303)
            page = login(client)
            self.assertEqual(page.status_code, 200, page.text)
            self.assertIn("Vault-Freigaben", page.text)
            self.assertTrue(capture[0].get("code_verifier"))
            self.assertEqual(capture[0]["redirect_uri"], [self.settings.public_url + "/auth/callback"])
            self.assertEqual(page.headers["referrer-policy"], "same-origin")
            self.assertNotIn("synthetic-oauth-access", page.headers.get("set-cookie", ""))
            response = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            self.assertEqual(response.status_code, 401, "Browser session cookie must not authorize MCP calls")

    def test_apply_command_is_static_readonly_and_owner_only(self):
        from html import unescape
        from ui import APPLY_COMMAND
        with self.client() as client:
            self.assertNotIn('id="apply-command"', client.get('/admin/').text)
            page = login(client)
            field = re.search(r'<textarea id="apply-command" readonly[^>]*>(.*?)</textarea>', page.text)
            self.assertIsNotNone(field)
            self.assertEqual(unescape(field.group(1)), APPLY_COMMAND)
            self.assertIn('config --quiet && ', APPLY_COMMAND)
            self.assertIn('up -d --remove-orphans', APPLY_COMMAND)
            self.assertNotIn(str(self.settings.vault_parent), APPLY_COMMAND)
            self.assertEqual(page.headers['cache-control'], 'no-store')
            for path in ('/mcp', '/mcp/'):
                response = client.post(path, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
                self.assertEqual(response.status_code, 401)

    def test_wrong_github_account_and_invalid_state_fail_closed(self):
        with self.client(owner=99999) as client:
            self.assertEqual(login(client).status_code, 403)
            self.assertEqual(client.get("/admin/", follow_redirects=False).status_code, 303)
        with self.client() as client:
            response = client.get("/auth/callback?code=synthetic&state=forged")
            self.assertEqual(response.status_code, 400)

    def test_csrf_other_origin_and_null_origin_are_rejected(self):
        with self.client() as client:
            page = login(client)
            for origin, token in ((self.settings.public_url, "bad"), ("https://evil.test", self.token(page)), ("null", self.token(page))):
                response = client.post("/admin/save", data={"csrf": token, "revision": "0"}, headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)

    def test_invalid_input_draft_and_empty_fields_are_preserved(self):
        with self.client() as client:
            page = login(client)
            data = {"csrf": self.token(page), "revision": "0", "vault_name": " Bad name ", "vault_label": "",
                    "vault_directory": "/srv/obsidian/vaults/New"}
            response = client.post("/admin/save", data=data, headers={"Origin": self.settings.public_url})
            self.assertEqual(response.status_code, 400)
            self.assertIn('value=" Bad name "', response.text)
            self.assertIn('name="vault_label" value=""', response.text)
            self.assertEqual(self.store.config()[0], 0)

    def test_ajax_errors_do_not_return_replacement_form_values(self):
        with self.client() as client:
            self.assertEqual(client.get("/admin/session").status_code, 401)
            login(client)
            response = client.get("/admin/session")
            self.assertEqual(response.headers['cache-control'], 'no-store')
            csrf = response.json()["csrf"]
            response = client.post("/admin/save", headers={"Accept": "application/json", "Origin": self.settings.public_url},
                data={"csrf": csrf, "revision": "0", "vault_name": " Bad ", "vault_label": "", "vault_directory": "/srv/obsidian/vaults/New"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(set(response.json()), {"message"})


class GatewayTests(Fixture):
    def setUp(self):
        super().setUp()
        self.vaults = self.save_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"},
            {"name": "strahd", "label": "D&D", "directory": "/srv/obsidian/vaults/Strahd"}])
        self.raw, self.identity = self.store.issue_client("Limited", [self.vaults[0]["id"]], 1)
        self.worker_calls = []

        def reply(request):
            self.worker_calls.append(request)
            return httpx2.Response(200, json={"paths": ["Session.md"]})
        self.app = create_app(self.settings, state=self.store, oauth_transport=github_transport(),
                              worker_transport=httpx2.MockTransport(reply))

    def rpc(self, client, method, params=None, token=None):
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers)

    def test_anonymous_and_forged_access_are_rejected_and_metadata_is_central(self):
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            for token in (None, "forged-token"):
                self.assertEqual(self.rpc(client, "tools/list", token=token).status_code, 401)
            metadata = client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["resource"], self.settings.public_url + "/mcp")
            self.assertEqual(client.get("/.well-known/oauth-authorization-server").json()["issuer"], self.settings.public_url + "/")

    def test_scoped_client_lists_only_allowed_vaults_and_cannot_switch(self):
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            response = self.rpc(client, "tools/call", {"name": "list_vaults", "arguments": {}}, self.raw)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("Memory", response.text)
            self.assertNotIn("D&D", response.text)
            self.assertNotIn("/srv/", response.text)
            response = self.rpc(client, "tools/call", {"name": "list_notes", "arguments": {"vault": "strahd"}}, self.raw)
            self.assertTrue(response.json()["result"]["isError"])
            self.assertEqual(self.worker_calls, [])
            response = self.rpc(client, "tools/call", {"name": "list_notes", "arguments": {"vault": "llm"}}, self.raw)
            self.assertFalse(response.json()["result"].get("isError", False), response.text)
            self.assertEqual(self.worker_calls[0].url.host, "vault-llm")
            self.assertEqual(self.worker_calls[0].headers["authorization"], "Bearer " + self.store.derive("worker:" + self.vaults[0]["id"]))
            self.store.revoke_client(self.identity)
            self.assertEqual(self.rpc(client, "tools/list", token=self.raw).status_code, 401)

    def test_github_verifier_does_not_accept_other_owner(self):
        async def check():
            provider = OwnerGitHubProvider(owner_id="12345", client_id="test", client_secret="synthetic-secret",
                                           base_url=self.settings.public_url, required_scopes=[])
            from unittest.mock import AsyncMock
            for owner in ("12345", "99999"):
                value = AccessToken(token="synthetic", client_id="test", scopes=[], claims={"sub": owner})
                with patch.object(GitHubProvider, "load_access_token", AsyncMock(return_value=value)):
                    self.assertEqual((await provider.load_access_token("synthetic")) is not None, owner == "12345")
        asyncio.run(check())


class BridgeTests(unittest.TestCase):
    def test_bridge_requires_clean_https_endpoint_and_credentials(self):
        env = {"MCP_SERVER_URL": "https://obsidian.test/mcp", "PANGOLIN_TOKEN_ID": "synthetic-id",
               "PANGOLIN_ACCESS_TOKEN": "synthetic-pangolin-credential", "MCP_CLIENT_TOKEN": "omcp_synthetic-local-test"}
        bridge = create_bridge(env)
        self.assertIsNotNone(bridge)
        for url in ("http://obsidian.test/mcp", "https://obsidian.test/mcp?p_token=secret", "https://user:secret@obsidian.test/mcp"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                create_bridge({**env, "MCP_SERVER_URL": url})


if __name__ == "__main__":
    unittest.main()
