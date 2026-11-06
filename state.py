"""Private local state, expiring capability tokens, and configuration revisions."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from vault import write_paths

NAME = re.compile(r"[a-z][a-z0-9-]{0,23}\Z")


class Conflict(ValueError):
    pass


class State:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        keyfile = self.directory / "master.key"
        try:
            fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if keyfile.is_symlink():
                raise ValueError("State key must not be a symlink")
        else:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_urlsafe(48))
        self.key = keyfile.read_text().encode("ascii")
        if len(self.key) < 40:
            raise ValueError("Invalid master key")
        self.db = self.directory / "state.sqlite3"
        if self.db.is_symlink():
            raise ValueError("State database must not be a symlink")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO config VALUES (1, 0, ?)", (json.dumps({"vaults": []}),))
            db.execute("CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, label TEXT NOT NULL, vault_ids TEXT NOT NULL, expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)")
            if 'write_grants' not in {row['name'] for row in db.execute('PRAGMA table_info(clients)')}:
                db.execute("ALTER TABLE clients ADD COLUMN write_grants TEXT NOT NULL DEFAULT '{}'")
        self.db.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def derive(self, purpose):
        return hmac.new(self.key, purpose.encode(), hashlib.sha256).hexdigest()

    def config(self):
        with self.connect() as db:
            row = db.execute("SELECT revision, data FROM config WHERE id=1").fetchone()
        return row["revision"], json.loads(row["data"])

    def prepare_vaults(self, items, parent):
        if len(items) > 50:
            raise ValueError("Maximal 50 Freigaben")
        _, previous = self.config()
        old = {v["name"]: v for v in previous["vaults"]}
        names, directories, result = set(), set(), []
        for item in items:
            name, label, directory = (str(item.get(k, "")) for k in ("name", "label", "directory"))
            if not NAME.fullmatch(name) or name in names:
                raise ValueError("URL-Namen: eindeutig, Kleinbuchstaben/Ziffern/Bindestriche, Beginn mit Buchstabe")
            if not label.strip() or len(label) > 100 or any(ord(c) < 32 for c in label):
                raise ValueError("Anzeigename fehlt, enthält Steuerzeichen oder ist zu lang")
            path = Path(directory)
            if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in directory):
                raise ValueError("Vault benötigt einen absoluten Serverpfad ohne ..")
            try:
                relative = path.relative_to(parent)
            except ValueError:
                raise ValueError("Vault muss unter VAULT_PARENT liegen") from None
            if not relative.parts or any(p.startswith(".") for p in relative.parts):
                raise ValueError("Einen sichtbaren einzelnen Vault oder Unterordner auswählen")
            canonical = str(path)
            if canonical in directories:
                raise ValueError("Dieses Verzeichnis wurde bereits freigegeben")
            names.add(name)
            directories.add(canonical)
            # A renamed or retargeted share is a new resource. Old capabilities
            # must not silently grant access to replacement content.
            previous = old.get(name)
            identity = previous["id"] if previous and Path(previous["directory"]) == path else uuid.uuid4().hex
            prefixes = item.get('write_paths', [])
            if isinstance(prefixes, str):
                prefixes = [line.strip() for line in prefixes.splitlines() if line.strip()]
            if 'write_enabled' in item:
                if not isinstance(item['write_enabled'], bool):
                    raise ValueError('Ungültige Schreibfreigabe')
                prefixes = (prefixes or ['/']) if item['write_enabled'] else []
            result.append({"id": identity, "name": name, "label": label, "directory": directory,
                           "write_paths": write_paths(prefixes)})
        return {"vaults": result}

    def save_config(self, config, expected_revision, write_deployment):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = db.execute("SELECT revision FROM config WHERE id=1").fetchone()[0]
            if revision != expected_revision:
                raise Conflict("Eine andere Sitzung hat gespeichert. Deine Eingaben bleiben erhalten; vor erneutem Speichern den aktuellen Stand vergleichen.")
            # Generate and fsync the deployment before acknowledging the change.
            write_deployment(config, revision + 1)
            db.execute("UPDATE config SET revision=?, data=? WHERE id=1", (revision + 1, json.dumps(config)))
        return revision + 1

    def issue_client(self, label, vault_ids, days, write_vault_ids=None):
        if not 1 <= days <= 90 or not label.strip() or len(label) > 100:
            raise ValueError("Client benötigt einen Namen und eine Laufzeit von 1 bis 90 Tagen")
        _, config = self.config()
        allowed = {v["id"] for v in config["vaults"]}
        chosen = set(vault_ids)
        if not chosen or not chosen <= allowed:
            raise ValueError("Mindestens eine vorhandene Freigabe auswählen")
        writable = set(write_vault_ids or [])
        if not writable <= chosen:
            raise ValueError('Schreibfreigaben benötigen auch Lesezugriff')
        grants = {v['id']: v.get('write_paths', []) for v in config['vaults'] if v['id'] in writable}
        if any(not paths for paths in grants.values()):
            raise ValueError('Schreiben zuerst für die betreffende Vault-Freigabe aktivieren')
        raw = "omcp_" + secrets.token_urlsafe(32)
        identity = uuid.uuid4().hex
        expires = int(time.time()) + days * 86400
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT INTO clients (id,digest,label,vault_ids,expires,write_grants) VALUES (?,?,?,?,?,?)",
                       (identity, digest, label, json.dumps(sorted(chosen)), expires, json.dumps(grants)))
        return raw, identity

    def verify_client(self, raw):
        if not raw.startswith("omcp_") or len(raw) > 200:
            return None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT * FROM clients WHERE digest=? AND revoked=0 AND expires>?", (digest, int(time.time()))).fetchone()
        if not row:
            return None
        return {"id": row["id"], "vault_ids": json.loads(row["vault_ids"]), "expires": row["expires"],
                "write_grants": json.loads(row['write_grants'])}

    def clients(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,label,expires,revoked,vault_ids FROM clients ORDER BY expires DESC")]

    def revoke_client(self, identity):
        with self.connect() as db:
            db.execute("UPDATE clients SET revoked=1 WHERE id=?", (identity,))
