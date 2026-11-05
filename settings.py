"""Deployment settings. No private addresses or credentials in source defaults."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    public_url: str
    github_client_id: str
    github_client_secret: str
    github_owner_id: str
    data_dir: Path
    override_file: Path
    vault_parent: Path
    mcp_public_url: str = ''
    mcp_origin_secret: str = ''

    @classmethod
    def load(cls, env=None):
        env = os.environ if env is None else env
        public = env["PUBLIC_URL"].rstrip("/")
        parsed = urlsplit(public)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("PUBLIC_URL must be an HTTPS origin without a path")
        authority = "[" + parsed.hostname + "]" if ":" in parsed.hostname else parsed.hostname
        public = "https://" + authority
        owner = env["GITHUB_OWNER_ID"]
        if not owner.isascii() or not owner.isdigit() or int(owner) <= 0:
            raise ValueError("GITHUB_OWNER_ID must be your numeric GitHub account ID")
        if not env["GITHUB_CLIENT_ID"] or not env["GITHUB_CLIENT_SECRET"]:
            raise ValueError("One central GitHub OAuth App is required")
        parent = Path(env.get("VAULT_PARENT", "/srv/obsidian/vaults"))
        if not parent.is_absolute() or ".." in parent.parts:
            raise ValueError("VAULT_PARENT must be an absolute host directory")
        direct = env.get('MCP_PUBLIC_URL', '').rstrip('/')
        origin_secret = env.get('MCP_ORIGIN_SECRET', '')
        if direct or origin_secret:
            parsed_direct = urlsplit(direct)
            if (parsed_direct.scheme != 'https' or not parsed_direct.hostname
                    or parsed_direct.username or parsed_direct.password or parsed_direct.path
                    or parsed_direct.query or parsed_direct.fragment or parsed_direct.port not in (None, 443)):
                raise ValueError('MCP_PUBLIC_URL must be an HTTPS origin without a path')
            direct_authority = '[' + parsed_direct.hostname + ']' if ':' in parsed_direct.hostname else parsed_direct.hostname
            direct = 'https://' + direct_authority
            if not 43 <= len(origin_secret) <= 256 or not origin_secret.isascii() or not all(c.isalnum() or c in '_-' for c in origin_secret):
                raise ValueError('Set a random URL-safe MCP_ORIGIN_SECRET of at least 43 characters')
        return cls(public, env["GITHUB_CLIENT_ID"], env["GITHUB_CLIENT_SECRET"], owner,
                   Path(env.get("DATA_DIR", "/data")),
                   Path(env.get("COMPOSE_OVERRIDE", "/deployment/compose.override.yaml")), parent,
                   direct, origin_secret)
