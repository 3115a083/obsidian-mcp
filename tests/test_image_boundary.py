"""Image-archive regression: a later deletion cannot hide a leaked file."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.check_image_boundary import check_archive


def layer_bytes(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, value in files.items():
            data = value.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


class ImageBoundaryTests(unittest.TestCase):
    def audit(self, layers, environment=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.tar"
            contents = {f"layer-{i}.tar": layer_bytes(files) for i, files in enumerate(layers)}
            contents["config.json"] = json.dumps({"config": {"Env": environment or []}}).encode()
            contents["manifest.json"] = json.dumps([{"Config": "config.json", "Layers": [f"layer-{i}.tar" for i in range(len(layers))]}]).encode()
            with tarfile.open(path, "w") as tar:
                for name, data in contents.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            check_archive(path)

    def test_application_source_and_generic_dependencies_are_allowed(self):
        self.audit([{"app/app.py": "# source", "usr/local/lib/python3.12/site-packages/example.py": "# dependency"}])

    def test_deleted_runtime_file_is_still_rejected(self):
        with self.assertRaises(ValueError):
            self.audit([{"app/.env": "SYNTHETIC=fixture"}, {"app/.wh..env": ""}])

    def test_credential_environment_and_note_mount_content_are_rejected(self):
        with self.assertRaises(ValueError):
            self.audit([{}], ["WORKER_TOKEN=synthetic-fixture"])
        with self.assertRaises(ValueError):
            self.audit([{"vault/Session.md": "synthetic private note"}])
