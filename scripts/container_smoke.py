"""Synthetic Docker integration test. Removes only its own random test resources."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE = "obsidian-mcp-ci:test"


def docker(*arguments, check=True):
    return subprocess.run(["docker", *arguments], check=check, capture_output=True, text=True).stdout.strip()


def main():
    identity = "omcp-ci-" + secrets.token_hex(6)
    app, worker, gateway, network, volume, notes = [identity + suffix for suffix in ("-app", "-worker", "-gateway", "-network", "-state", "-notes")]
    try:
        docker("network", "create", network)
        docker("volume", "create", volume)
        docker("volume", "create", notes)
        docker("run", "--rm", "--network", "none", "--user", "0:0", "--mount", f"type=volume,source={volume},target=/data", IMAGE,
               "python", "-c", "import os;os.chown('/data',568,568)")
        docker("run", "--rm", "--network", "none", "--user", "0:0", "--mount", f"type=volume,source={notes},target=/vault", IMAGE,
               "python", "-c", "from pathlib import Path;p=Path('/vault/Session.md');p.write_text('Synthetic safe session');p.chmod(0o444)")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            override = root / "compose.override.yaml"
            override.write_text("services: {}\n")
            # Ephemeral synthetic CI file, shared with non-root test container only.
            override.chmod(0o666)
            app_env = root / "app.env"
            app_env.write_text("MCP_IMAGE=obsidian-mcp-ci:test\nMCP_GATEWAY_IMAGE=obsidian-mcp-gateway-ci:test\nPUBLIC_URL=https://obsidian.test\nGITHUB_CLIENT_ID=synthetic-ci-client\nGITHUB_CLIENT_SECRET=synthetic-ci-secret\nGITHUB_OWNER_ID=12345\nVAULT_PARENT=/srv/obsidian/vaults\n")
            app_env.chmod(0o600)
            docker("run", "-d", "--name", app, "--network", network, "--network-alias", "app", "--read-only", "--cap-drop", "ALL",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--security-opt", "no-new-privileges:true",
                   "--env-file", str(app_env), "--mount", f"type=volume,source={volume},target=/data",
                   "--mount", f"type=bind,source={override},target=/deployment/compose.override.yaml", IMAGE)
            repo = Path(__file__).resolve().parents[1]
            nginx_image = "obsidian-mcp-gateway-ci:test"
            docker("run", "-d", "--name", gateway, "--network", network, "--read-only", "--user", "568:568", "--cap-drop", "ALL",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "-p", "127.0.0.1::8080", "--entrypoint", "nginx",
                   "--mount", f"type=bind,source={repo / 'nginx.conf'},target=/etc/nginx/nginx.conf,readonly",
                   nginx_image, "-c", "/etc/nginx/nginx.conf", "-g", "daemon off;")
            address = docker("port", gateway, "8080/tcp").splitlines()[0]
            endpoint = "http://" + address

            def request(path, data=None, token=None):
                headers = {"Host": "obsidian.test", "Accept": "application/json, text/event-stream"}
                if token:
                    headers["Authorization"] = "Bearer " + token
                if data is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(endpoint + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=3) as response:
                        return response.status, response.read()
                except urllib.error.HTTPError as error:
                    return error.code, error.read()

            deadline = time.monotonic() + 45
            while True:
                try:
                    status, body = request("/healthz")
                    if status == 200:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic application container did not become ready")
                time.sleep(0.25)
            assert json.loads(body)["version"] == "2.0.0"
            assert request("/login")[0] == 200
            assert request("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0] == 401
            code = """import json
from pathlib import Path
from state import State
from deployment import write_override
s=State('/data')
c=s.prepare_vaults([{'name':'llm','label':'Synthetic memory','directory':'/srv/obsidian/vaults/${OTHER_ROOT}/$campaign'}],Path('/srv/obsidian/vaults'))
s.save_config(c,0,lambda data,revision:write_override(Path('/deployment/compose.override.yaml'),data,s,revision))
t,i=s.issue_client('Synthetic CI',[c['vaults'][0]['id']],1)
print(json.dumps({'token':t,'id':i,'worker':s.derive('worker:'+c['vaults'][0]['id'])}))
"""
            credentials = json.loads(docker("exec", app, "python", "-c", code))
            # Validate the generated file through real Compose interpolation.
            rendered = json.loads(docker("compose", "--env-file", str(app_env), "-f", str(repo / "compose.yaml"),
                                         "-f", str(override), "config", "--format", "json"))
            # Canonical config output may re-escape dollars for re-reading.
            source = rendered["services"]["vault-llm"]["volumes"][0]["source"]
            assert source.replace("$$", "$") == "/srv/obsidian/vaults/${OTHER_ROOT}/$campaign", repr(source)
            worker_env = root / "worker.env"
            worker_env.write_text("WORKER_TOKEN=" + credentials["worker"] + "\nVAULT_ROOT=/vault\n")
            worker_env.chmod(0o600)
            docker("run", "-d", "--name", worker, "--network", network, "--network-alias", "vault-llm", "--read-only", "--cap-drop", "ALL",
                   "--env-file", str(worker_env), "--mount", f"type=volume,source={notes},target=/vault,readonly", IMAGE,
                   "uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log")
            rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_note", "arguments": {"vault": "llm", "path": "Session.md"}}}
            deadline = time.monotonic() + 20
            while True:
                status, body = request("/mcp", rpc, credentials["token"])
                if status == 200 and b"Synthetic safe session" in body:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic MCP-to-worker read failed")
                time.sleep(0.25)
            check = "from pathlib import Path\ntry:\n Path('/vault/new.md').write_text('must fail')\nexcept OSError:\n print('read-only enforced')\nelse:\n raise SystemExit('Vault was writable')"
            assert docker("exec", worker, "python", "-c", check) == "read-only enforced"
            assert docker("inspect", "--format", "{{.HostConfig.ReadonlyRootfs}}", worker) == "true"
            docker("exec", app, "python", "-c", "from state import State;State('/data').revoke_client('" + credentials["id"] + "')")
            assert request("/mcp", rpc, credentials["token"])[0] == 401
            print("Docker smoke passed: Nginx proxy, non-root app, scoped MCP read, worker authentication, read-only mount and immediate revocation.")
    finally:
        for name in (gateway, app, worker):
            docker("rm", "--force", name, check=False)
        for name in (volume, notes):
            docker("volume", "rm", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
