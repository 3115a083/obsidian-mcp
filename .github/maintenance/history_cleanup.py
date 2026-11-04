"""One-time, owner-authorized cleanup with exact ref leases and no runtime data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

PLAN = json.loads(r'''{
  "source_main": "75013a5980e69742c590e0d5023582575fb95a07",
  "source_tree": "504df85ca2a7c72960b28b81bc3e3e9c547ac791",
  "source_refs": [
    [
      "refs/heads/dependabot/docker/python-3.15-alpine",
      "e920d98105cbc4ca30215957f1723f14657de3dd"
    ],
    [
      "refs/heads/dependabot/github_actions/actions/checkout-7.0.1",
      "ed1dd38c405904569ef63a8b87acf1b6a2d4b081"
    ],
    [
      "refs/heads/dependabot/github_actions/actions/setup-python-7.1.0",
      "cf56e100ff9ad724c2acff18639abc2d64927fe9"
    ],
    [
      "refs/heads/dependabot/github_actions/aquasecurity/trivy-action-0.36.0",
      "ee0b0c5f3d9d9076eae4294db3419f29c5f08efc"
    ],
    [
      "refs/heads/feat/central-auth-and-private-images",
      "f9598ffa649152e2bccedf1ac11b51d6231a7685"
    ],
    [
      "refs/heads/main",
      "75013a5980e69742c590e0d5023582575fb95a07"
    ],
    [
      "refs/heads/security/public-repository-hardening",
      "035352f8739ddde29b4e5e979519fd50dd877a86"
    ],
    [
      "refs/heads/security/release-audit",
      "574768d3236582010df4377c7da3a55208242fb1"
    ]
  ],
  "clean_refs": [
    [
      "refs/heads/dependabot/docker/python-3.15-alpine",
      "95052bd4e5a42bd2f80a6cfc21a329e5351b1fc4"
    ],
    [
      "refs/heads/dependabot/github_actions/actions/checkout-7.0.1",
      "c739bd89b1c688695f997de47839f2de6b523b6a"
    ],
    [
      "refs/heads/dependabot/github_actions/actions/setup-python-7.1.0",
      "95ec60de983645f6d5d478041a36112b5ab5edcb"
    ],
    [
      "refs/heads/dependabot/github_actions/aquasecurity/trivy-action-0.36.0",
      "c535c69d5be4d43145bddd8694441411c29f3e20"
    ],
    [
      "refs/heads/feat/central-auth-and-private-images",
      "a60aa0ddc01200e3e5e42896a8e8467448d7e399"
    ],
    [
      "refs/heads/main",
      "cd03c81c9b315f54b7949eb1ec754dbf4c40a031"
    ],
    [
      "refs/heads/security/public-repository-hardening",
      "4e5d182935ae8d8a59e41af6840992403db9e7fc"
    ],
    [
      "refs/heads/security/release-audit",
      "4054738867dd1cadbd59f86d80da9202c17e87dc"
    ]
  ],
  "remove_line_sha256": [
    "2f27de149ed7d739ebf4f2a990c691378639466494b3cc2cb3c9be617013bb81",
    "8c2ecd915eac9332155f60ab3089eda056e056b658d74432291193175c4fe556",
    "e5f008a6fec36abeddb2a13b7070cab53404fec5c716153cf335fb2aa5045296"
  ]
}''')
PLAN["source_refs"] = dict(PLAN["source_refs"])
PLAN["clean_refs"] = dict(PLAN["clean_refs"])
REPOSITORY = "3115a083/obsidian-mcp"
RULESET = 26446573
TEMP_BRANCH = "refs/heads/maintenance/history-cleanup"
REMOVE_PATHS = (".github/workflows/history-cleanup.yml", ".github/maintenance/history_cleanup.py")
SCANNER_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
SCANNER_URL = "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz"

def run(args, *, cwd=None, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit("Required operation failed: " + args[0])
    return result.stdout

def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise SystemExit("Only explicit manual dispatch is permitted")
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SystemExit("Unexpected repository")
    if os.environ.get("GITHUB_ACTOR_ID") != os.environ.get("GITHUB_REPOSITORY_OWNER_ID"):
        raise SystemExit("Only the repository owner may start this operation")
    if os.environ.get("GITHUB_TRIGGERING_ACTOR") != os.environ.get("GITHUB_REPOSITORY_OWNER"):
        raise SystemExit("Only the repository owner may rerun this operation")
    if str(event.get("inputs", {}).get("confirm", "")).lower() != "true":
        raise SystemExit("Explicit dispatch confirmation missing")
    expected = dict(PLAN["source_refs"])
    expected["refs/heads/main"] = os.environ["GITHUB_SHA"]
    workspace = Path(tempfile.mkdtemp(prefix="history-cleanup-", dir=os.environ["RUNNER_TEMP"]))
    mirror = workspace / "mirror.git"
    run(["git", "clone", "--mirror", "https://github.com/" + REPOSITORY + ".git", str(mirror)])
    def git(*args, env=None):
        return run(["git", *args], cwd=mirror, env=env)
    def refs():
        return dict(line.split(" ", 1)[::-1] for line in git("for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags").decode().splitlines())
    observed = refs()
    if set(observed) != set(expected) | {TEMP_BRANCH}:
        raise SystemExit("Unexpected branch/tag set, refusing any write")
    for ref, sha in expected.items():
        if observed[ref] != sha:
            raise SystemExit("A reviewed branch changed, refusing any write: " + ref)
    source_tree = PLAN["source_tree"]
    for ref in ("refs/heads/main", TEMP_BRANCH):
        tree = git("rev-parse", ref + "^{tree}").decode().strip()
        stripped = git("ls-tree", "-r", ref).decode().splitlines()
        expected_entries = git("ls-tree", "-r", PLAN["source_main"]).decode().splitlines()
        stripped = [line for line in stripped if line.split("\t", 1)[1] not in REMOVE_PATHS]
        if stripped != expected_entries:
            raise SystemExit("Maintenance source differs from the reviewed release")
    # The local original-history bundle was verified before this owner-authorized run.
    # Create a second ephemeral backup before filtering. Do not publish old-history artifacts.
    git("bundle", "create", str(workspace / "before.bundle"), "--all")
    hashes = set(PLAN["remove_line_sha256"])
    if not all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
        raise SystemExit("Invalid removal digest")
    expression = "import hashlib\nremove = " + repr(hashes) + "\n"
    blob_callback = expression + "blob.data = b''.join(line for line in blob.data.splitlines(keepends=True) if hashlib.sha256(line).hexdigest() not in remove)"
    message_callback = expression + "return b''.join(line for line in message.splitlines(keepends=True) if hashlib.sha256(line).hexdigest() not in remove)"
    args = ["filter-repo"]
    for path in REMOVE_PATHS:
        args += ["--path", path]
    args += ["--invert-paths", "--blob-callback", blob_callback, "--message-callback", message_callback]
    git(*args)
    cleaned = refs()
    for ref, sha in PLAN["clean_refs"].items():
        if cleaned.get(ref) != sha:
            raise SystemExit("Sanitized commit differs from the separately reviewed mirror: " + ref)
    if git("rev-parse", "refs/heads/main^{tree}").decode().strip() != source_tree:
        raise SystemExit("Current release tree changed")
    archive = workspace / "gitleaks.tar.gz"
    with urllib.request.urlopen(SCANNER_URL, timeout=60) as response:
        archive.write_bytes(response.read(32 * 1024 * 1024 + 1))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SCANNER_SHA256:
        raise SystemExit("Scanner checksum mismatch")
    scanner = workspace / "gitleaks"
    with tarfile.open(archive) as tar:
        member = tar.getmember("gitleaks")
        if not member.isfile() or member.size > 64 * 1024 * 1024:
            raise SystemExit("Unexpected scanner archive")
        scanner.write_bytes(tar.extractfile(member).read())
    scanner.chmod(0o700)
    run([str(scanner), "git", "--redact", "--no-banner", "--log-opts=--all", str(mirror)])
    state = {"mirror": str(mirror), "observed": observed, "sha": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"]}
    Path(os.environ["RUNNER_TEMP"], "history-cleanup-state.json").write_text(json.dumps(state))
    print("PREPARATION_VERIFIED", flush=True)

def apply():
    state = json.loads(Path(os.environ["RUNNER_TEMP"], "history-cleanup-state.json").read_text())
    if state["sha"] != os.environ["GITHUB_SHA"] or state["run"] != os.environ["GITHUB_RUN_ID"]:
        raise SystemExit("Prepared state belongs to a different run")
    if os.environ.get("GITHUB_ACTOR_ID") != os.environ.get("GITHUB_REPOSITORY_OWNER_ID"):
        raise SystemExit("Only the repository owner may apply this operation")
    mirror = Path(state["mirror"])
    observed = state["observed"]
    def git(*args, env=None):
        return run(["git", *args], cwd=mirror, env=env)
    # No credentials are installed until preparation has passed.
    encoded = base64.b64encode(("x-access-token:" + os.environ["GH_TOKEN"]).encode()).decode()
    print("::add-mask::" + encoded, flush=True)
    push_env = dict(os.environ)
    push_env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + encoded})
    summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    summary.write_text("## History cleanup ready\n\nReviewed sanitized Main: " + PLAN["clean_refs"]["refs/heads/main"] + "\n\nAll branch leases and the current release tree passed. Waiting at most ten minutes for the owner's temporary Main-ruleset suspension.\n")
    print("READY_FOR_AUTHORIZED_RULESET_WINDOW", flush=True)
    endpoint = "https://api.github.com/repos/" + REPOSITORY + "/rulesets/" + str(RULESET)
    for _ in range(120):
        with urllib.request.urlopen(endpoint, timeout=20) as response:
            enforcement = json.load(response).get("enforcement")
        if enforcement == "disabled":
            break
        if enforcement != "active":
            raise SystemExit("Unexpected ruleset state")
        time.sleep(5)
    else:
        raise SystemExit("Ruleset window not opened; no remote history changed")
    command = ["push", "--atomic"]
    for ref, sha in observed.items():
        command.append("--force-with-lease=" + ref + ":" + sha)
    command.append("https://github.com/" + REPOSITORY + ".git")
    for ref in PLAN["clean_refs"]:
        command.append(ref + ":" + ref)
    command.append(":" + TEMP_BRANCH)
    git(*command, env=push_env)
    advertised = git("ls-remote", "--heads", "--tags", "https://github.com/" + REPOSITORY + ".git").decode().splitlines()
    remote = dict(line.split("\t", 1)[::-1] for line in advertised)
    if remote != PLAN["clean_refs"]:
        raise SystemExit("Post-push ref verification failed; restore protection immediately")
    with summary.open("a") as file:
        file.write("\nAtomic history update verified. Restore the active Main ruleset immediately.\n")
    print("HISTORY_UPDATE_VERIFIED_RESTORE_RULESET", flush=True)

if __name__ == "__main__":
    apply() if sys.argv[1:] == ["apply"] else main()

