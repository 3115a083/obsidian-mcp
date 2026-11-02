"""One-time local setup of runtime files. No Docker API or network access."""
import os
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
data = root / "data"
override = root / "compose.override.yaml"
if data.is_symlink() or override.is_symlink():
    raise SystemExit("Runtime paths must not be symbolic links")
data.mkdir(mode=0o700, exist_ok=True)
if not override.exists():
    shutil.copyfile(root / "compose.override.example.yaml", override)
override.chmod(0o600)
uid, gid = int(os.environ.get("MCP_UID", 568)), int(os.environ.get("MCP_GID", 568))
if uid <= 0 or gid <= 0:
    raise SystemExit("Use non-root container IDs")
if os.geteuid() == 0:
    os.chown(data, uid, gid)
    os.chown(override, uid, gid)
else:
    print("Ensure data/ and compose.override.yaml are writable by the configured MCP_UID/MCP_GID.")
print("Runtime files prepared. No vaults created or modified.")
