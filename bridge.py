"""STDIO MCP bridge: adds Pangolin credentials before reaching its protected proxy.

Use as the command behind a private Secure MCP Tunnel or in a local MCP client.
Never expose this unauthenticated STDIO endpoint as a public HTTP service.
"""
import os
from urllib.parse import urlsplit
import httpx2
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.server import create_proxy


def create_bridge(env=None, *, upstream_transport=None):
    env = os.environ if env is None else env
    url = env["MCP_SERVER_URL"]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/mcp"):
        raise ValueError("MCP_SERVER_URL must be an HTTPS /mcp endpoint without query credentials")
    headers = {"P-Access-Token-Id": env["PANGOLIN_TOKEN_ID"], "P-Access-Token": env["PANGOLIN_ACCESS_TOKEN"]}
    token = env["MCP_CLIENT_TOKEN"]
    if any(not value or any(ord(c) < 32 for c in value) for value in [*headers.values(), token]):
        raise ValueError("Missing or invalid bridge credentials")
    if not token.startswith("omcp_"):
        raise ValueError("Use a scoped vault access token from the administration GUI")

    def client_factory(**kwargs):
        # An upstream redirect must not forward Pangolin headers to another host.
        kwargs.update(follow_redirects=False, trust_env=False, verify=True)
        if upstream_transport is not None:
            kwargs["transport"] = upstream_transport
        return httpx2.AsyncClient(**kwargs)

    transport = StreamableHttpTransport(url, headers=headers, auth=token,
                                       httpx_client_factory=client_factory)
    return create_proxy(transport, name="Protected Obsidian Bridge")


if __name__ == "__main__":
    create_bridge().run(transport="stdio", show_banner=False)
