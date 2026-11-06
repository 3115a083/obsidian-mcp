"""Scoped Markdown changes through normal worker and authenticated MCP routes."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import httpx2
from starlette.testclient import TestClient

from app import create_app
from deployment import compose_override
from state import State
from tests.support import github_transport, login, settings_for
from vault import NoteConflict, Vault
from worker import create_worker


class NoteWritingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = Vault(self.root, ['Project'])

    def test_create_update_patch_move_and_restore_preserve_history(self):
        created = self.vault.create_note('Project/Session.md', '# Session\nDraft\n')
        self.assertEqual(self.vault.read_note(created['path'])['revision'], created['revision'])
        changed = self.vault.patch_note(created['path'], 'Draft', 'Confirmed', created['revision'])
        self.assertEqual(self.vault.read_note(created['path'])['lines'][1], 'Confirmed')
        versions = self.vault.list_note_versions(created['path'])['versions']
        self.assertEqual(versions[0]['revision'], created['revision'])
        self.assertEqual(self.vault.search_notes('Draft')['matches'], [])
        self.assertEqual(self.vault.list_notes()['paths'], ['Project/Session.md'])
        self.vault.restore_note(created['path'], created['revision'], changed['revision'])
        self.vault.move_note(created['path'], 'Project/Archive/Session.md', created['revision'])
        self.assertFalse((self.root / created['path']).exists())
        self.vault.restore_note(created['path'], created['revision'], 'missing')
        self.assertEqual(self.vault.read_note(created['path'])['lines'][1], 'Draft')

    def test_stale_edits_existing_destinations_and_partial_moves_keep_data(self):
        created = self.vault.create_note('Project/A.md', 'one')
        self.vault.update_note('Project/A.md', 'two', created['revision'])
        with self.assertRaises(NoteConflict):
            self.vault.update_note('Project/A.md', 'three', created['revision'])
        with self.assertRaises(NoteConflict):
            self.vault.create_note('Project/A.md', 'different')
        self.assertEqual(self.vault.create_note('Project/A.md', 'two')['revision'], hashlib.sha256(b'two').hexdigest())
        with self.assertRaises(NoteConflict):
            self.vault.patch_note('Project/A.md', 'missing', 'new', self.vault.read_note('Project/A.md')['revision'])
        self.vault.create_note('Project/B.md', 'existing')
        current = self.vault.read_note('Project/A.md')['revision']
        with self.assertRaises(NoteConflict):
            self.vault.move_note('Project/A.md', 'Project/B.md', current)
        with patch('vault.os.unlink', side_effect=PermissionError('synthetic failure')):
            with self.assertRaises(PermissionError):
                self.vault.move_note('Project/A.md', 'Project/C.md', current)
        self.assertEqual((self.root / 'Project/A.md').read_text(), 'two')
        self.assertEqual((self.root / 'Project/B.md').read_text(), 'existing')

    def test_scope_symlinks_hardlinks_hidden_paths_and_special_files_fail_closed(self):
        for path in ('Other/A.md', 'Project-other/A.md', '../A.md', 'Project/.obsidian/a.md', 'Project/x.txt'):
            with self.subTest(path=path), self.assertRaises((ValueError, PermissionError)):
                self.vault.create_note(path, 'blocked')
        (self.root / 'Project').mkdir()
        (self.root / 'outside').mkdir()
        (self.root / 'Project/link').symlink_to(self.root / 'outside', target_is_directory=True)
        with self.assertRaises(OSError):
            self.vault.create_note('Project/link/A.md', 'blocked')
        (self.root / 'outside/A.md').write_text('untouched')
        os.link(self.root / 'outside/A.md', self.root / 'Project/hard.md')
        with self.assertRaises(ValueError):
            self.vault.update_note('Project/hard.md', 'blocked', hashlib.sha256(b'untouched').hexdigest())
        os.mkfifo(self.root / 'Project/pipe.md')
        with self.assertRaises(ValueError):
            self.vault.update_note('Project/pipe.md', 'blocked', 'forged')
        self.assertEqual((self.root / 'outside/A.md').read_text(), 'untouched')
        with self.assertRaises(PermissionError):
            Vault(self.root).create_note('Project/A.md', 'blocked')

    def test_history_failure_and_concurrent_updates_do_not_lose_note(self):
        original = self.vault.create_note('Project/A.md', 'original')
        with patch.object(self.vault, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.vault.update_note('Project/A.md', 'failed', original['revision'])
        self.assertEqual((self.root / 'Project/A.md').read_text(), 'original')

        def edit(text):
            try:
                return self.vault.update_note('Project/A.md', text, original['revision'])
            except NoteConflict:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, ['first', 'second']))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertIn((self.root / 'Project/A.md').read_text(), ['first', 'second'])

    def test_bom_restore_is_byte_exact_and_existing_snapshot_links_are_rejected(self):
        content = '\ufeff# Heading\nOriginal\r\n'
        created = self.vault.create_note('Project/A.md', content)
        changed = self.vault.patch_note('Project/A.md', 'Original', 'Changed', created['revision'])
        self.assertTrue((self.root / 'Project/A.md').read_bytes().startswith(b'\xef\xbb\xbf'))
        self.vault.restore_note('Project/A.md', created['revision'], changed['revision'])
        self.assertEqual((self.root / 'Project/A.md').read_bytes(), content.encode())
        snapshot = self.root / '.mcp-history' / (hashlib.sha256(b'Project/A.md').hexdigest() + '-' + created['revision'] + '.md')
        snapshot.unlink()
        snapshot.symlink_to(self.root / 'Project/A.md')
        with self.assertRaises(OSError):
            self.vault.update_note('Project/A.md', 'blocked', created['revision'])
        self.assertEqual((self.root / 'Project/A.md').read_bytes(), content.encode())

    def test_write_size_and_worker_permission_and_conflict_status(self):
        worker = create_worker(self.root, 'k' * 64, ['Project'])
        headers = {'Authorization': 'Bearer ' + 'k' * 64}
        with TestClient(worker) as client:
            self.assertEqual(client.post('/create_note', json={'path': 'Project/A.md', 'content': 'x'}).status_code, 401)
            self.assertEqual(client.post('/create_note', headers=headers, json={'path': 'Other/A.md', 'content': 'x'}).status_code, 403)
            content = 'Synthetic long Markdown line\n' * 5000
            result = client.post('/create_note', headers=headers, json={'path': 'Project/A.md', 'content': content})
            self.assertEqual(result.status_code, 200, result.text)
            result = client.post('/update_note', headers=headers, json={'path': 'Project/A.md', 'content': 'new', 'expected_revision': 'stale'})
            self.assertEqual(result.status_code, 409)
        for content in ('\x00', 'x' * 16001, 'line\n' * (500000)):
            with self.assertRaises(ValueError):
                self.vault.create_note('Project/Large.md', content)


class GatewayWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = settings_for(self.root)
        self.state = State(self.settings.data_dir)
        self.items = [{'name': 'memory', 'label': 'Memory', 'directory': '/srv/obsidian/vaults/memory',
                       'write_paths': ['Project']},
                      {'name': 'notes', 'label': 'Notes', 'directory': '/srv/obsidian/vaults/notes'}]
        self.configure()
        self.vault_id = self.state.config()[1]['vaults'][0]['id']
        self.read_token, _ = self.state.issue_client('Read', [self.vault_id], 1)
        self.write_token, self.client_id = self.state.issue_client('Write', [self.vault_id], 1, [self.vault_id])
        self.vault_root = self.root / 'vault'
        self.vault_root.mkdir()
        worker = create_worker(self.vault_root, self.state.derive('worker:' + self.vault_id), ['Project', 'Other'])
        self.app = create_app(self.settings, state=self.state, oauth_transport=github_transport(),
                              worker_transport=httpx2.ASGITransport(worker))

    def configure(self):
        config = self.state.prepare_vaults(self.items, self.settings.vault_parent)
        self.state.save_config(config, self.state.config()[0], lambda *_: None)

    def call(self, client, name, arguments, token):
        return client.post('/mcp', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'},
                           json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                 'params': {'name': name, 'arguments': arguments}})

    def test_capabilities_scopes_policy_changes_and_revocation(self):
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            args = {'vault': 'memory', 'path': 'Project/A.md', 'content': 'confirmed'}
            self.assertTrue(self.call(client, 'create_note', args, self.read_token).json()['result']['isError'])
            self.assertFalse(self.call(client, 'create_note', args, self.write_token).json()['result'].get('isError', False))
            self.assertTrue(self.call(client, 'create_note', {**args, 'vault': 'notes'}, self.write_token).json()['result']['isError'])
            self.items[0]['write_paths'] = ['/']
            self.configure()
            self.assertTrue(self.call(client, 'create_note', {**args, 'path': 'Other/A.md'}, self.write_token).json()['result']['isError'])
            self.items[0]['write_paths'] = []
            self.configure()
            self.assertTrue(self.call(client, 'create_note', args, self.write_token).json()['result']['isError'])
            self.state.revoke_client(self.client_id)
            self.assertEqual(self.call(client, 'create_note', args, self.write_token).status_code, 401)

    def test_optin_compose_and_raw_invalid_write_folder_draft(self):
        config = self.state.config()[1]
        services = json.loads(compose_override(config, self.state, 1).split('\n', 1)[1])['services']
        self.assertFalse(services['vault-memory']['volumes'][0]['read_only'])
        self.assertTrue(services['vault-notes']['volumes'][0]['read_only'])
        self.assertTrue(services['vault-memory']['read_only'])
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            page = login(client)
            import re
            csrf = re.search('name="csrf" value="([^"]+)"', page.text).group(1)
            response = client.post('/admin/save', data={'csrf': csrf, 'revision': '1',
                'vault_name': 'memory', 'vault_label': 'Memory', 'vault_directory': self.items[0]['directory'],
                'vault_write_paths': '  ../invalid  \n'}, headers={'Origin': self.settings.public_url})
            self.assertEqual(response.status_code, 400)
            self.assertIn('  ../invalid  \n</textarea>', response.text)
            self.assertEqual(self.state.config()[0], 1)

    def test_existing_client_schema_migrates_to_readonly_grants(self):
        database = self.root / 'old'
        database.mkdir()
        with sqlite3.connect(database / 'state.sqlite3') as db:
            db.execute('CREATE TABLE clients (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, label TEXT NOT NULL, vault_ids TEXT NOT NULL, expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)')
        state = State(database)
        with state.connect() as db:
            self.assertIn('write_grants', {row['name'] for row in db.execute('PRAGMA table_info(clients)')})

    def test_checkbox_rows_enable_and_disable_without_affecting_other_vaults(self):
        import re
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            page = login(client)
            csrf = re.search('name="csrf" value="([^"]+)"', page.text).group(1)
            keys = re.findall('name="vault_row_key" value="([^"]+)"', page.text)[:2]
            self.assertEqual(len(keys), 2)
            fields = {'csrf': csrf, 'revision': '1', 'vault_name': ['memory', 'notes'],
                      'vault_label': ['Memory', 'Notes'],
                      'vault_directory': [item['directory'] for item in self.items],
                      'vault_write_paths': ['', ''], 'vault_row_key': keys,
                      'vault_writable': keys[0]}
            response = client.post('/admin/save', data=fields, headers={'Origin': self.settings.public_url}, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            self.assertEqual([v['write_paths'] for v in self.state.config()[1]['vaults']], [['/'], []])
            # An unchecked browser checkbox is omitted from the POST. Row keys
            # bind it to the correct vault without shifting later rows.
            fields.pop('vault_writable')
            fields['revision'] = '2'
            response = client.post('/admin/save', data=fields, headers={'Origin': self.settings.public_url}, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            self.assertEqual([v['write_paths'] for v in self.state.config()[1]['vaults']], [[], []])
            fields['vault_writable'] = 'unknown-row'
            fields['revision'] = '3'
            self.assertEqual(client.post('/admin/save', data=fields, headers={'Origin': self.settings.public_url}).status_code, 400)
            self.assertEqual(self.state.config()[0], 3)

    def test_checkbox_preserves_saved_custom_folder_and_invalid_checked_draft(self):
        from ui import vault_row
        import re
        html = vault_row(self.state.config()[1]['vaults'][0], self.settings.vault_parent)
        self.assertRegex(html, 'name="vault_writable" value="[^"]+" checked')
        self.assertIn('Project</textarea>', html)
        config = self.state.prepare_vaults([{**self.items[0], 'write_enabled': False}], self.settings.vault_parent)
        self.assertEqual(config['vaults'][0]['write_paths'], [])
        with TestClient(self.app, base_url=self.settings.public_url) as client:
            page = login(client)
            csrf = re.search('name="csrf" value="([^"]+)"', page.text).group(1)
            result = client.post('/admin/save', data={'csrf': csrf, 'revision': '1',
                'vault_name': 'memory', 'vault_label': 'Memory', 'vault_directory': self.items[0]['directory'],
                'vault_row_key': 'row1', 'vault_writable': 'row1', 'vault_write_paths': '  ../invalid  \n'},
                headers={'Origin': self.settings.public_url})
            self.assertEqual(result.status_code, 400)
            self.assertIn('  ../invalid  \n</textarea>', result.text)
            self.assertRegex(result.text, 'name="vault_writable" value="[^"]+" checked')


if __name__ == '__main__':
    unittest.main()
