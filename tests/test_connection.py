"""Synthetic direct ChatGPT OAuth and ingress boundary regressions."""
import asyncio
import base64
from dataclasses import replace
import hashlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx2
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider
from starlette.testclient import TestClient

from app import create_app
from connection import DirectAccessGuard
from settings import Settings
from state import State
from tests.support import github_transport, login, settings_for

ORIGIN = 'https://chatgpt.obsidian.test'
SECRET = 'synthetic-origin-secret-' + 'x' * 48
HEADERS = {'X-Obsidian-Connection': 'direct', 'X-Pangolin-Origin': SECRET}
REDIRECT = 'https://chatgpt.com/connector/oauth/synthetic-obsidian'


class DirectConnectionTests(unittest.TestCase):
    origin = ORIGIN
    marker = "direct"

    @property
    def headers(self):
        return {**HEADERS, "X-Obsidian-Connection": self.marker}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = replace(settings_for(self.temp.name), mcp_public_url=self.origin, mcp_origin_secret=SECRET)
        self.store = State(self.settings.data_dir)
        config = self.store.prepare_vaults([{'name': 'memory', 'label': 'Synthetic memory',
            'directory': '/srv/obsidian/vaults/example'}], self.settings.vault_parent)
        self.store.save_config(config, 0, lambda *_: None)
        self.static, _ = self.store.issue_client('Synthetic limited client', [config['vaults'][0]['id']], 1)
        self.app = create_app(self.settings, state=self.store, oauth_transport=github_transport())

    def client(self):
        return TestClient(self.app, base_url=self.origin, headers=self.headers)

    def rpc(self, client, method='tools/list', token=None, params=None):
        headers = {'Accept': 'application/json, text/event-stream'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        return client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1,
            'method': method, 'params': params or {}})

    def register(self, client, redirect=REDIRECT):
        return client.post('/register', json={'client_name': 'Synthetic ChatGPT',
            'redirect_uris': [redirect], 'token_endpoint_auth_method': 'none',
            'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})

    def test_routes_require_origin_and_marker_and_never_expose_admin(self):
        with self.client() as client:
            self.assertEqual(client.get('/healthz').status_code, 200)
            for path in ('/admin/', '/login', '/auth/login', '/admin/session'):
                self.assertEqual(client.get(path).status_code, 404, path)
            self.assertEqual(client.get('/healthz', headers={'X-Obsidian-Connection': 'legacy'}).status_code, 404)
            self.assertEqual(client.get(self.settings.public_url + '/admin/', follow_redirects=False).status_code, 404)
            client.headers.pop('X-Pangolin-Origin')
            self.assertEqual(client.get('/healthz').status_code, 200)
            self.assertEqual(client.get('/.well-known/oauth-authorization-server').status_code, 403)
            client.headers.pop('X-Obsidian-Connection')
            self.assertEqual(client.get('/healthz').status_code, 404)

    def test_metadata_and_challenge_use_the_direct_origin(self):
        with self.client() as client:
            resource = client.get('/.well-known/oauth-protected-resource/mcp').json()
            self.assertEqual(resource['resource'], self.origin + '/mcp')
            metadata = client.get('/.well-known/oauth-authorization-server').json()
            self.assertEqual(metadata['issuer'], self.origin + '/')
            self.assertIn('S256', metadata['code_challenge_methods_supported'])
            for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'):
                self.assertTrue(metadata[key].startswith(self.origin + '/'), metadata)
            response = self.rpc(client)
            self.assertEqual(response.status_code, 401)
            self.assertIn(self.origin, response.headers['www-authenticate'])

    def test_legacy_tokens_and_browser_cookies_cannot_authenticate_direct_mcp(self):
        with self.client() as client:
            client.cookies.set('omcp_session', 'synthetic-forged-cookie')
            for token in (None, 'forged-token', self.static):
                self.assertEqual(self.rpc(client, token=token).status_code, 401)
            legacy = client.post(self.settings.public_url + '/mcp', headers={
                'X-Obsidian-Connection': 'legacy', 'Authorization': 'Bearer ' + self.static,
                'Accept': 'application/json, text/event-stream'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            self.assertEqual(legacy.status_code, 200)

    def test_owner_authorization_and_readonly_tools_are_preserved(self):
        with self.client() as client:
            for owner in ('12345', '99999'):
                access = AccessToken(token='synthetic', client_id='test', scopes=[], claims={'sub': owner})
                with patch.object(GitHubProvider, 'load_access_token', AsyncMock(return_value=access)):
                    response = self.rpc(client, token='synthetic')
                    self.assertEqual(response.status_code, 200 if owner == '12345' else 401)
                    if owner != '12345':
                        continue
                    tools = response.json()['result']['tools']
                    self.assertEqual({tool['name'] for tool in tools}, {'list_vaults', 'list_notes', 'read_note', 'search_notes'})
                    self.assertTrue(all(tool['annotations']['readOnlyHint'] for tool in tools))
                    response = self.rpc(client, 'tools/call', 'synthetic', {'name': 'list_vaults', 'arguments': {}})
                    self.assertIn('Synthetic memory', response.text)
                    self.assertNotIn('/srv/', response.text)

    def test_registration_redirects_csrf_and_rate_limit(self):
        with self.client() as client:
            self.assertEqual(self.register(client, 'https://attacker.test/callback').status_code, 400)
            self.assertEqual(self.register(client).status_code, 201)
            self.assertEqual(client.get('/auth/mcp/callback?state=forged&code=forged').status_code, 400)
            self.assertEqual(client.post('/consent', data={'txn_id': 'forged', 'action': 'approve'}).status_code, 400)
            statuses = [self.register(client).status_code for _ in range(10)]
            self.assertIn(429, statuses)

    def test_full_oauth_pkce_consent_and_code_replay(self):
        from fastmcp.server.auth.providers import github
        http_client = httpx2.AsyncClient
        transport = github_transport()
        with patch.object(github.httpx2, 'AsyncClient', side_effect=lambda *a, **kw: http_client(*a, **kw, transport=transport)), \
             self.client() as client:
            registration = self.register(client).json()
            verifier = 'synthetic-pkce-verifier-' + 'a' * 48
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            response = client.get('/authorize', params={'client_id': registration['client_id'],
                'redirect_uri': REDIRECT, 'response_type': 'code', 'state': 'client-state',
                'code_challenge': challenge, 'code_challenge_method': 'S256', 'resource': self.origin + '/mcp'}, follow_redirects=False)
            self.assertIn(response.status_code, (302, 303), response.text)
            consent = client.get(response.headers['location'])
            fields = {name: re.search(r'name="' + name + r'"\s+value="([^"]+)"', consent.text).group(1)
                      for name in ('txn_id', 'csrf_token')}
            # A different browser cannot approve a consent page it did not open.
            stranger = TestClient(self.app, base_url=self.origin, headers=self.headers)
            self.assertEqual(stranger.post('/consent', data={**fields, 'action': 'approve'}).status_code, 403)
            stranger.close()
            response = client.post('/consent', data={**fields, 'action': 'approve'}, headers={'Origin': self.origin}, follow_redirects=False)
            self.assertIn(response.status_code, (302, 303), response.text)
            upstream = parse_qs(urlsplit(response.headers['location']).query)
            self.assertEqual(upstream['redirect_uri'], [self.origin + '/auth/mcp/callback'])
            response = client.get('/auth/mcp/callback', params={'state': upstream['state'][0], 'code': 'synthetic-code'}, follow_redirects=False)
            self.assertIn(response.status_code, (302, 303), response.text)
            returned = parse_qs(urlsplit(response.headers['location']).query)
            self.assertEqual(returned['state'], ['client-state'])
            data = {'grant_type': 'authorization_code', 'client_id': registration['client_id'],
                'code': returned['code'][0], 'redirect_uri': REDIRECT, 'code_verifier': verifier,
                'resource': self.origin + '/mcp'}
            invalid = client.post('/token', data={**data, 'code_verifier': 'wrong-' + verifier})
            self.assertIn(invalid.status_code, (400, 401))
            token = client.post('/token', data=data)
            self.assertEqual(token.status_code, 200, token.text)
            self.assertEqual(self.rpc(client, token=token.json()['access_token']).status_code, 200)
            self.assertEqual(client.post('/token', data=data).status_code, 401)


class SharedOriginConnectionTests(DirectConnectionTests):
    origin = 'https://obsidian.test'
    marker = 'legacy'

    def test_routes_require_origin_and_marker_and_never_expose_admin(self):
        with self.client() as client:
            self.assertEqual(client.get('/healthz').status_code, 200)
            self.assertEqual(client.get('/login').status_code, 200)
            self.assertEqual(client.get('/admin/', follow_redirects=False).status_code, 303)
            self.assertEqual(client.get('/admin/session').status_code, 401)
            for path in ('/mcp-admin', '/authorize-admin', '/.well-known/admin', '/auth/mcp/callback-extra'):
                self.assertEqual(client.get(path).status_code, 404, path)
            self.assertEqual(client.get('/healthz', headers={'X-Obsidian-Connection': 'direct'}).status_code, 404)
            client.headers.pop('X-Pangolin-Origin')
            self.assertEqual(client.get('/login').status_code, 200)
            self.assertEqual(client.get('/.well-known/oauth-authorization-server').status_code, 403)

    def test_legacy_tokens_and_browser_cookies_cannot_authenticate_direct_mcp(self):
        with self.client() as client:
            self.assertEqual(login(client).status_code, 200)
            self.assertIn('omcp_session', client.cookies)
            for token in (None, 'forged-token', self.static):
                self.assertEqual(self.rpc(client, token=token).status_code, 401)


class ConnectionSettingsTests(unittest.TestCase):
    def test_opt_in_is_complete_and_separate(self):
        env = {'PUBLIC_URL': 'https://admin.test', 'GITHUB_OWNER_ID': '12345',
               'GITHUB_CLIENT_ID': 'synthetic', 'GITHUB_CLIENT_SECRET': 'synthetic'}
        self.assertEqual(Settings.load(env).mcp_public_url, '')
        for changes in ({'MCP_PUBLIC_URL': ORIGIN}, {'MCP_ORIGIN_SECRET': SECRET},
                        {'MCP_PUBLIC_URL': 'http://mcp.test', 'MCP_ORIGIN_SECRET': SECRET},
                        {'MCP_PUBLIC_URL': ORIGIN + '/mcp', 'MCP_ORIGIN_SECRET': SECRET},
                        {'MCP_PUBLIC_URL': ORIGIN, 'MCP_ORIGIN_SECRET': 'short'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Settings.load({**env, **changes})
        self.assertEqual(Settings.load({**env, 'MCP_PUBLIC_URL': ORIGIN, 'MCP_ORIGIN_SECRET': SECRET}).mcp_public_url, ORIGIN)
        self.assertEqual(Settings.load({**env, 'MCP_PUBLIC_URL': env['PUBLIC_URL'], 'MCP_ORIGIN_SECRET': SECRET}).mcp_public_url, env['PUBLIC_URL'])

    def test_disabled_connection_rejects_direct_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = settings_for(directory)
            with TestClient(create_app(settings), base_url=settings.public_url, headers=HEADERS) as client:
                self.assertEqual(client.get('/healthz').status_code, 404)


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, guard, *, path='/mcp', headers=(), chunks=None):
        events = iter(chunks or [{'type': 'http.request', 'body': b''}])
        received = []
        async def receive():
            return next(events)
        async def send(event):
            received.append(event)
        await guard({'type': 'http', 'method': 'POST', 'path': path,
            'headers': [(b'x-pangolin-origin', SECRET.encode()), *headers]}, receive, send)
        return received[0]['status']

    async def test_bounds_streams_lengths_concurrency_and_state(self):
        async def app(scope, receive, send):
            await receive()
            await send({'type': 'http.response.start', 'status': 204})
        with tempfile.TemporaryDirectory() as directory:
            guard = DirectAccessGuard(app, secret=SECRET, state_dir=directory, max_state_bytes=32)
            self.assertEqual(await self.request(guard), 204)
            for lengths, status in (([b'-1'], 400), ([b'bad'], 400), ([b'1', b'1'], 400), ([b'65537'], 413)):
                self.assertEqual(await self.request(guard, headers=[(b'content-length', value) for value in lengths]), status)
            self.assertEqual(await self.request(guard, chunks=[{'type': 'http.request', 'body': b'x' * 65537}]), 413)
            guard.active = 8
            self.assertEqual(await self.request(guard), 503)
            guard.active = 0
            Path(directory, 'synthetic').write_bytes(b'x' * 33)
            self.assertEqual(await self.request(guard, path='/register'), 503)
            self.assertEqual(await self.request(guard), 204)
            self.assertEqual(guard.active, 0)
