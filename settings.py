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
        return cls(public, env["GITHUB_CLIENT_ID"], env["GITHUB_CLIENT_SECRET"], owner,
                   Path(env.get("DATA_DIR", "/data")),
                   Path(env.get("COMPOSE_OVERRIDE", "/deployment/compose.override.yaml")), parent)
