"""Audit image metadata and every layer, including files deleted later.

Does not run the image or extract archive paths onto the filesystem. This is
an application/runtime boundary check, complementary to Trivy secret scanning.
"""
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

APP_FILES = {"requirements.txt", "app.py", "auth.py", "bridge.py", "connection.py", "deployment.py",
             "settings.py", "state.py", "ui.py", "vault.py", "web.py", "worker.py"}
RUNTIME_FILES = {".env", "master.key", "state.sqlite3", "bridge.env", "compose.override.yaml"}


def check_archive(path):
    with tarfile.open(path, "r:*") as archive:
        manifests = json.load(archive.extractfile("manifest.json"))
        for manifest in manifests:
            config = json.load(archive.extractfile(manifest["Config"]))
            for item in config.get("config", {}).get("Env", []):
                name = item.split("=", 1)[0]
                if re.search(r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|ACCESS_KEY)", name, re.I):
                    raise ValueError("Runtime credential variable baked into image metadata")
            for layer_name in manifest["Layers"]:
                with tarfile.open(fileobj=archive.extractfile(layer_name), mode="r|*") as layer:
                    for member in layer:
                        if member.isdir():
                            continue
                        path = PurePosixPath(member.name.removeprefix("./").lstrip("/"))
                        if path.name in RUNTIME_FILES or path.parts[:1] in (("data",), ("vault",), ("vaults",)):
                            raise ValueError("Runtime state or credential file found in an image layer")
                        if path.parts[:1] == ("app",) and str(path.relative_to("app")) not in APP_FILES:
                            raise ValueError("Unexpected application file found in an image layer")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check_image_boundary.py IMAGE")
    with tempfile.TemporaryDirectory(prefix="obsidian-image-audit-") as directory:
        archive = Path(directory) / "image.tar"
        subprocess.run(["docker", "image", "save", "--output", str(archive), sys.argv[1]], check=True)
        check_archive(archive)
    print("Image boundary passed: no runtime credential/state files in metadata or layers; application files allowlisted.")


if __name__ == "__main__":
    main()
