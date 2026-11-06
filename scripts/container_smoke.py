"""Synthetic Docker integration test. Removes only its own random test resources."""
import json
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE = "obsidian-mcp-ci:test"


def docker(*arguments, check=True, environment=None):
    return subprocess.run(["docker", *arguments], check=check, capture_output=True, text=True,
                          env=environment).stdout.strip()


def recovery_smoke():
    """A failed real bind mount cannot prevent a base-only admin start."""
    identity = 'omcp-recovery-' + secrets.token_hex(6)
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copyfile(repo / 'compose.yaml', root / 'compose.yaml')
        (root / 'data').mkdir(mode=0o700)
        override = root / 'compose.override.yaml'
        missing = root / 'missing-vault'
        override.write_text(json.dumps({'services': {'vault-broken': {
            'image': IMAGE, 'command': ['python', '-c', 'pass'],
            'volumes': [{'type': 'bind', 'source': str(missing), 'target': '/vault',
                         'read_only': True, 'bind': {'create_host_path': False}}]}}}))
        override.chmod(0o600)
        uid, gid = os.getuid() or 568, os.getgid() or 568
        env = root / '.env'
        env.write_text('MCP_IMAGE=' + IMAGE + '\nMCP_GATEWAY_IMAGE=obsidian-mcp-gateway-ci:test\n'
            'PUBLIC_URL=https://recovery.test\nGITHUB_CLIENT_ID=synthetic-ci-client\n'
            'GITHUB_CLIENT_SECRET=synthetic-ci-secret\nGITHUB_OWNER_ID=12345\n'
            'VAULT_PARENT=/srv/obsidian/vaults\nMCP_GATEWAY_PORT=0\n'
            f'MCP_UID={uid}\nMCP_GID={gid}\n')
        env.chmod(0o600)
        docker('run', '--rm', '--network', 'none', '--user', '0:0',
            '--mount', f'type=bind,source={root / "data"},target=/data',
            '--mount', f'type=bind,source={override},target=/override', IMAGE,
            'python', '-c', f"import os;os.chown('/data',{uid},{gid});os.chown('/override',{uid},{gid})")

        def compose(*args, check=True):
            return subprocess.run(['docker', 'compose', '-p', identity, *args], cwd=root,
                                  check=check, capture_output=True, text=True)
        try:
            failed = compose('-f', 'compose.yaml', '-f', 'compose.override.yaml',
                             'up', '-d', 'vault-broken', check=False)
            assert failed.returncode != 0 and not missing.exists(), 'Missing bind source must fail without being created'
            # Exact recovery command from the UI, with a private test project.
            compose('-f', 'compose.yaml', 'up', '-d', 'app', 'gateway')
            address = compose('-f', 'compose.yaml', 'port', 'gateway', '8080').stdout.strip()
            deadline = time.monotonic() + 45
            while True:
                try:
                    request = urllib.request.Request('http://' + address + '/login', headers={'Host': 'recovery.test'})
                    with urllib.request.urlopen(request, timeout=3) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Admin recovery after failed vault mount did not become ready')
                time.sleep(0.25)
            assert override.exists() and 'vault-broken' in override.read_text()
            assert (root / 'data' / 'master.key').exists()
            assert not missing.exists()
            print('Recovery smoke passed: failed bind mount, independent admin startup, packaged gateway configuration and preserved state.')
        finally:
            compose('-f', 'compose.yaml', '-f', 'compose.override.yaml', 'down', '--remove-orphans', check=False)



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
            origin_secret = secrets.token_urlsafe(48)
            app_env = root / "app.env"
            app_env.write_text("MCP_IMAGE=obsidian-mcp-ci:test\nMCP_GATEWAY_IMAGE=obsidian-mcp-gateway-ci:test\nPUBLIC_URL=https://obsidian.test\nGITHUB_CLIENT_ID=synthetic-ci-client\nGITHUB_CLIENT_SECRET=synthetic-ci-secret\nGITHUB_OWNER_ID=12345\nVAULT_PARENT=/srv/obsidian/vaults\n")
            with app_env.open("a") as handle:
                handle.write("MCP_PUBLIC_URL=https://chatgpt.obsidian.test\n")
            app_env.chmod(0o600)
            def start_app():
                docker("run", "-d", "--name", app, "--network", network, "--network-alias", "app", "--read-only", "--cap-drop", "ALL",
                       "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--security-opt", "no-new-privileges:true",
                       "--env-file", str(app_env), "--env", "MCP_ORIGIN_SECRET",
                       "--mount", f"type=volume,source={volume},target=/data",
                       "--mount", f"type=bind,source={override},target=/deployment/compose.override.yaml", IMAGE,
                       environment={**os.environ, 'MCP_ORIGIN_SECRET': origin_secret})
            start_app()
            repo = Path(__file__).resolve().parents[1]
            nginx_image = "obsidian-mcp-gateway-ci:test"
            docker("run", "-d", "--name", gateway, "--network", network, "--read-only", "--user", "568:568", "--cap-drop", "ALL",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "-p", "127.0.0.1::8080", "-p", "127.0.0.1::8081", "--entrypoint", "nginx",
                   nginx_image, "-c", "/etc/nginx/nginx.conf", "-g", "daemon off;")
            address = docker("port", gateway, "8080/tcp").splitlines()[0]
            endpoint = "http://" + address

            direct_endpoint = "http://" + docker("port", gateway, "8081/tcp").splitlines()[0]

            def request(path, data=None, token=None, *, direct=False, host=None, origin=True, marker=None):
                headers = {"Host": host or ("chatgpt.obsidian.test" if direct else "obsidian.test"), "Accept": "application/json, text/event-stream"}
                if origin:
                    headers["X-Pangolin-Origin"] = origin_secret
                if marker:
                    headers["X-Obsidian-Connection"] = marker
                if token:
                    headers["Authorization"] = "Bearer " + token
                if data is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request((direct_endpoint if direct else endpoint) + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=3) as response:
                        if path == "/healthz":
                            assert response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
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
            assert json.loads(body)["version"] == "2.2.0"
            assert request("/login")[0] == 200
            assert request("/healthz", direct=True)[0] == 200
            assert request("/.well-known/oauth-authorization-server", direct=True, origin=False)[0] == 403
            status, body = request("/.well-known/oauth-authorization-server", direct=True)
            assert status == 200 and json.loads(body)["issuer"] == "https://chatgpt.obsidian.test/"
            status, body = request("/.well-known/oauth-protected-resource/mcp", direct=True)
            assert status == 200 and json.loads(body)["resource"] == "https://chatgpt.obsidian.test/mcp"
            assert request("/admin/", direct=True)[0] == 404
            assert request("/admin/", direct=True, host="obsidian.test", marker="legacy")[0] == 404
            assert request("/healthz", host="chatgpt.obsidian.test", marker="direct")[0] == 404
            assert request("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, direct=True)[0] == 401
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
            assert request("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, credentials["token"], direct=True)[0] == 401
            # Validate the generated file through real Compose interpolation.
            rendered = json.loads(docker("compose", "--env-file", str(app_env), "-f", str(repo / "compose.yaml"),
                                         "-f", str(override), "config", "--format", "json"))
            # Check actual Compose parsing, including the comma-containing tmpfs
            # option. An unquoted flow list silently splits it into four mounts.
            for service_name in ("app", "gateway", "vault-llm"):
                service = rendered["services"][service_name]
                assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=32m"], service_name
                assert service["read_only"] is True, service_name
                assert service["cap_drop"] == ["ALL"], service_name
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
            # Opt in on the same existing share. Exercise real network/tool,
            # worker and writable bind boundaries, not just local functions.
            code = """import json
from pathlib import Path
from state import State
from deployment import write_override
s=State('/data')
revision,c=s.config()
c['vaults'][0]['write_paths']=['Project']
s.save_config(c,revision,lambda data,rev:write_override(Path('/deployment/compose.override.yaml'),data,s,rev))
t,i=s.issue_client('Synthetic write CI',[c['vaults'][0]['id']],1,[c['vaults'][0]['id']])
print(json.dumps({'token':t,'id':i}))
"""
            write_credentials = json.loads(docker('exec', app, 'python', '-c', code))
            docker('rm', '--force', worker)
            docker('run', '--rm', '--network', 'none', '--user', '0:0',
                   '--mount', f'type=volume,source={notes},target=/vault', IMAGE,
                   'python', '-c', "import os;os.chown('/vault',568,568)")
            worker_env.write_text(worker_env.read_text() + 'VAULT_WRITE_PATHS=["Project"]\n')
            docker('run', '-d', '--name', worker, '--network', network, '--network-alias', 'vault-llm',
                   '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--env-file', str(worker_env), '--mount', f'type=volume,source={notes},target=/vault', IMAGE,
                   'uvicorn', 'worker:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log')

            def write_call(name, arguments, token=write_credentials['token']):
                status, payload = request('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': name, 'arguments': {'vault': 'llm', **arguments}}}, token)
                assert status == 200, status
                return json.loads(payload)['result']

            content = '# Synthetic write\n' + 'Long session paragraph\n' * 5000
            arguments = {'path': 'Project/Session.md', 'content': content}
            deadline = time.monotonic() + 20
            while write_call('create_note', arguments).get('isError'):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Writable worker did not become ready')
                time.sleep(0.25)
            assert write_call('create_note', {**arguments, 'path': 'Other/blocked.md'}).get('isError')
            assert write_call('create_note', arguments, token=credentials['token']).get('isError')
            old_revision = hashlib.sha256(content.encode()).hexdigest()
            updated = 'Confirmed synthetic event\n'
            result = write_call('update_note', {'path': arguments['path'], 'content': updated, 'expected_revision': old_revision})
            assert not result.get('isError'), result
            assert write_call('update_note', {'path': arguments['path'], 'content': 'stale', 'expected_revision': old_revision}).get('isError')
            result = write_call('list_note_versions', {'path': arguments['path']})
            assert old_revision in json.dumps(result)
            result = write_call('restore_note', {'path': arguments['path'], 'revision': old_revision,
                'expected_revision': hashlib.sha256(updated.encode()).hexdigest()})
            assert not result.get('isError'), result
            result = write_call('move_note', {'path': arguments['path'], 'destination': 'Project/Archive/Session.md', 'expected_revision': old_revision})
            assert not result.get('isError'), result
            docker('exec', app, 'python', '-c', "from state import State;State('/data').revoke_client('" + write_credentials['id'] + "')")
            assert request('/mcp', rpc, write_credentials['token'])[0] == 401
            docker("exec", app, "python", "-c", "from state import State;State('/data').revoke_client('" + credentials["id"] + "')")
            assert request("/mcp", rpc, credentials["token"])[0] == 401
            # Reuse the same public host and port, preserving admin sessions,
            # while the exact machine paths switch to OAuth-only protection.
            docker("rm", "--force", app)
            app_env.write_text(app_env.read_text().replace("MCP_PUBLIC_URL=https://chatgpt.obsidian.test", "MCP_PUBLIC_URL=https://obsidian.test"))
            start_app()
            deadline = time.monotonic() + 45
            while True:
                try:
                    if request("/healthz")[0] == 200:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Shared-origin application did not become ready")
                time.sleep(0.25)
            assert request("/login")[0] == 200
            assert request("/.well-known/oauth-authorization-server", origin=False)[0] == 403
            status, body = request("/.well-known/oauth-protected-resource/mcp")
            assert status == 200 and json.loads(body)["resource"] == "https://obsidian.test/mcp"
            assert request("/mcp", rpc, credentials["token"])[0] == 401
            status, body = request("/register", {"client_name": "Synthetic ChatGPT", "redirect_uris": ["https://chatgpt.com/connector/oauth/synthetic-container"], "token_endpoint_auth_method": "none", "grant_types": ["authorization_code"], "response_types": ["code"]})
            assert status == 201, (status, body)
            assert request("/healthz", direct=True, host="obsidian.test", marker="legacy")[0] == 404
            print("Docker smoke passed: same-origin admin/OAuth routing, optional separate OAuth ingress, Host/header spoof rejection, Nginx proxy, non-root app, scoped MCP read, worker authentication, read-only mount and immediate revocation.")
    finally:
        for name in (gateway, app, worker):
            docker("rm", "--force", name, check=False)
        for name in (volume, notes):
            docker("volume", "rm", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
    recovery_smoke()
