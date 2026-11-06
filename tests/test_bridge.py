import asyncio
from pathlib import Path
import tempfile
import unittest
import httpx2
from fastmcp import Client
from starlette.responses import PlainTextResponse, RedirectResponse
from app import create_app
from bridge import create_bridge
from deployment import write_override
from state import State
from tests.support import github_transport, settings_for


class PangolinBridgeTests(unittest.TestCase):
    def test_bridge_supplies_both_auth_layers_on_every_request(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                settings = settings_for(Path(directory))
                state = State(settings.data_dir)
                config = state.prepare_vaults([{"name": "llm", "label": "Memory", "directory": "/srv/obsidian/vaults/LLMs"}], settings.vault_parent)
                state.save_config(config, 0, lambda data, revision: write_override(settings.override_file, data, state, revision))
                token, identity = state.issue_client("Bridge", [config["vaults"][0]["id"]], 1)
                main = create_app(settings, state=state, oauth_transport=github_transport())
                requests = []

                async def protected(scope, receive, send):
                    if scope["type"] != "http":
                        return await main(scope, receive, send)
                    headers = dict(scope["headers"])
                    requests.append(headers)
                    if (headers.get(b"p-access-token-id") != b"synthetic-id" or
                            headers.get(b"p-access-token") != b"synthetic-pangolin-secret"):
                        return await PlainTextResponse("Pangolin denied", status_code=401)(scope, receive, send)
                    return await main(scope, receive, send)

                env = {"MCP_SERVER_URL": settings.public_url + "/mcp", "PANGOLIN_TOKEN_ID": "synthetic-id",
                       "PANGOLIN_ACCESS_TOKEN": "synthetic-pangolin-secret", "MCP_CLIENT_TOKEN": token}
                bridge = create_bridge(env, upstream_transport=httpx2.ASGITransport(app=protected))
                async with main.router.lifespan_context(main):
                    async with Client(bridge) as client:
                        tools = await client.list_tools()
                        self.assertEqual({tool.name for tool in tools}, {'list_vaults', 'list_notes', 'read_note', 'search_notes', 'list_note_versions', 'create_note', 'update_note', 'patch_note', 'move_note', 'restore_note'})
                        result = await client.call_tool("list_vaults")
                        self.assertIn("Memory", str(result))
                self.assertGreaterEqual(len(requests), 2)
                for headers in requests:
                    self.assertEqual(headers.get(b"p-access-token-id"), b"synthetic-id")
                    self.assertEqual(headers.get(b"authorization"), ("Bearer " + token).encode())
        asyncio.run(run())

    def test_redirect_cannot_leak_headers_to_another_origin(self):
        async def run():
            hosts = []

            async def redirect(scope, receive, send):
                hosts.append(dict(scope["headers"]).get(b"host"))
                return await RedirectResponse("https://attacker.test/mcp", status_code=307)(scope, receive, send)

            env = {"MCP_SERVER_URL": "https://obsidian.test/mcp", "PANGOLIN_TOKEN_ID": "synthetic-id",
                   "PANGOLIN_ACCESS_TOKEN": "synthetic-pangolin-secret", "MCP_CLIENT_TOKEN": "omcp_synthetic-test-only"}
            bridge = create_bridge(env, upstream_transport=httpx2.ASGITransport(app=redirect))
            async with Client(bridge) as client:
                self.assertEqual(await client.list_tools(), [])
            self.assertTrue(hosts)
            self.assertNotIn(b"attacker.test", hosts)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
