"""Generate only explicit, read-only vault services for Compose's override file."""
import fcntl
import json
import os


def compose_override(config, state, revision):
    services = {}
    for vault in config["vaults"]:
        name = vault["name"]
        services["vault-" + name] = {
            "image": "${MCP_IMAGE:?Set MCP_IMAGE}",
            "user": "${MCP_UID:-568}:${MCP_GID:-568}",
            "command": ["uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"],  # nosec B104 # Private internal Docker network; no published worker ports; deployment tests enforce this.
            "environment": {"WORKER_TOKEN": state.derive("worker:" + vault["id"]), "VAULT_ROOT": "/vault", "HOME": "/tmp"},  # nosec B108 # HOME is a per-container tmpfs, not a predictable temporary file.
            "volumes": [{"type": "bind", "source": vault["directory"], "target": "/vault", "read_only": True,
                         "bind": {"create_host_path": False}}],
            "networks": ["backplane"], "read_only": True,
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=32m"], "cap_drop": ["ALL"],  # nosec B108 # Declares the isolated tmpfs mount itself; no host temp-file API.
            "security_opt": ["no-new-privileges:true"], "pids_limit": 96,
            "mem_limit": "256m", "cpus": 1.0, "restart": "unless-stopped",
            "labels": {"obsidian-mcp.vault-id": vault["id"]},
        }
    # JSON is valid YAML. No credential or path is interpreted as YAML code.
    return "# Generated locally; contains worker credentials. Never commit. Revision " + str(revision) + "\n" + json.dumps({"services": services}, ensure_ascii=False, indent=2) + "\n"


def write_override(path, config, state, revision):
    content = compose_override(config, state, revision)
    # The file is an explicit bind mount, so replace-in-place is required.
    # Keep a recovery copy in private state. No Docker API is called here.
    backup = state.directory / "deployment.previous.yaml"
    if path.exists():
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    with path.open("r+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        file.seek(0)
        file.write(content)
        file.truncate()
        file.flush()
        os.fsync(file.fileno())
