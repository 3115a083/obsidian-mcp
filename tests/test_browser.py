"""Real browser regression: GitHub callback, cookies, CSRF and editable drafts.

Only synthetic provider replies and an ephemeral local test TLS key are used.
No test route or provider override is shipped in the production image.
"""
import datetime
import base64
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright
import uvicorn
import httpx2

from app import create_app
from tests.support import github_transport, settings_for


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "Run explicitly with RUN_BROWSER_TESTS=1 after installing Chromium")
class RealBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
        keyfile, certfile = root / "test-key.pem", root / "test-cert.pem"
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        self.origin = f"https://localhost:{port}"
        settings = settings_for(root, self.origin)
        self.direct_origin = f'https://127.0.0.1:{port}'
        self.origin_secret = 'synthetic-browser-origin-' + 'x' * 48
        settings = replace(settings, mcp_public_url=self.direct_origin, mcp_origin_secret=self.origin_secret)
        self.application = create_app(settings, oauth_transport=github_transport())
        self.server = uvicorn.Server(uvicorn.Config(self.application, host="127.0.0.1", port=port,
            ssl_keyfile=str(keyfile), ssl_certfile=str(certfile), log_level="error", access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [listener]}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.server.started, "Synthetic browser test server did not start")

    def stop_server(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def test_direct_oauth_consent_in_real_browser(self):
        from fastmcp.server.auth.providers import github
        client_class = httpx2.AsyncClient
        transport = github_transport()
        callback = 'https://chatgpt.com/connector/oauth/synthetic-browser'
        verifier = 'synthetic-browser-verifier-' + 'x' * 48
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with patch.object(github.httpx2, 'AsyncClient', side_effect=lambda *a, **kw: client_class(*a, **kw, transport=transport)), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(ignore_https_errors=True, extra_http_headers={
                    'X-Obsidian-Connection': 'direct', 'X-Pangolin-Origin': self.origin_secret})
                registration = context.request.post(self.direct_origin + '/register', data={
                    'client_name': 'Synthetic browser', 'redirect_uris': [callback],
                    'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code'],
                    'response_types': ['code']})
                self.assertEqual(registration.status, 201, registration.text())
                page = context.new_page()
                def redirect_boundary(route, link_id):
                    # Exercise the real browser POST, Origin, CSRF and cookies.
                    # Chromium does not re-route an external redirect hop, so
                    # make only the provider boundary a fresh link navigation.
                    response = route.fetch(max_redirects=0)
                    self.assertIn(response.status, (302, 303), response.text())
                    target = response.headers['location'].replace('&', '&amp;')
                    route.fulfill(response=response, status=200,
                        headers={**{key: value for key, value in response.headers.items()
                                    if key not in ('content-length', 'location')}, 'content-type': 'text/html'},
                        body='<a id="' + link_id + '" href="' + target + '">Continue</a>')
                page.route(self.direct_origin + '/consent', lambda route: redirect_boundary(route, 'provider-start'))
                page.route(self.direct_origin + '/auth/mcp/callback?**', lambda route: redirect_boundary(route, 'client-return'))
                def github_redirect(route):
                    query = parse_qs(urlsplit(route.request.url).query)
                    target = query['redirect_uri'][0] + '?' + urlencode({'state': query['state'][0], 'code': 'synthetic-code'})
                    route.fulfill(status=200, content_type='text/html', body='<a id="continue" href="' + target.replace('&', '&amp;') + '">Continue</a>')
                page.route('https://github.com/login/oauth/authorize**', github_redirect)
                page.route(callback + '**', lambda route: route.fulfill(status=200, body='Synthetic OAuth completion'))
                page.goto(self.direct_origin + '/authorize?' + urlencode({
                    'client_id': registration.json()['client_id'], 'redirect_uri': callback,
                    'response_type': 'code', 'state': 'synthetic-browser-state',
                    'code_challenge': challenge, 'code_challenge_method': 'S256',
                    'resource': self.direct_origin + '/mcp'}))
                self.assertTrue(page.locator('[name="csrf_token"]').input_value())
                page.locator('button[value="approve"]').click()
                page.locator('#provider-start').click()
                page.locator('#continue').click()
                page.locator('#client-return').click()
                page.wait_for_url(callback + '**')
                query = parse_qs(urlsplit(page.url).query)
                self.assertEqual(query['state'], ['synthetic-browser-state'])
                self.assertTrue(query['code'][0])
            finally:
                browser.close()

    def test_browser_login_and_csrf_submission_and_draft_preservation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                # Test-only self-signed localhost TLS certificate, never production TLS.
                context = browser.new_context(ignore_https_errors=True, viewport={"width": 1200, "height": 1000})
                page = context.new_page()
                failures = []
                page.on("pageerror", lambda error: failures.append(str(error)))

                def fake_github(route):
                    # Chromium routing does not re-intercept a redirect chain.
                    # Fetch the real local login endpoint, preserve its signed
                    # session cookie, then replace only the provider's browser hop.
                    upstream = route.fetch(max_redirects=0)
                    destination = urlsplit(upstream.headers["location"])
                    self.assertEqual(destination.netloc, "github.com")
                    self.assertEqual(destination.path, "/login/oauth/authorize")
                    values = parse_qs(destination.query)
                    self.assertEqual(values["code_challenge_method"], ["S256"])
                    headers = dict(upstream.headers)
                    headers["location"] = self.origin + "/auth/callback?" + urlencode({"code": "synthetic-code", "state": values["state"][0]})
                    route.fulfill(response=upstream, headers=headers)
                page.route(self.origin + "/auth/login", fake_github)
                page.goto(self.origin + "/login")
                page.get_by_role("link", name="Mit GitHub fortfahren").click()
                page.wait_for_url(self.origin + "/admin/")
                self.assertEqual(page.get_by_role("heading", name="Vault-Freigaben").count(), 1)
                session = next(c for c in context.cookies() if c["name"] == "omcp_session")
                self.assertTrue(session["secure"])
                self.assertTrue(session["httpOnly"])
                self.assertEqual(session["sameSite"], "Lax")
                page.get_by_role("button", name="+ Vault hinzufügen").click()
                page.locator('[name="vault_name"]').fill("llm")
                page.locator('[name="vault_label"]').fill("Synthetic memory")
                page.locator('[name="vault_directory"]').fill("/srv/obsidian/vaults/LLMs")
                seen_origins = []
                page.on("request", lambda request: seen_origins.append(request.headers.get("origin")) if request.method == "POST" and request.url.endswith("/admin/save") else None)
                page.get_by_role("button", name="Konfiguration speichern", exact=True).click()
                page.locator('#save-status').wait_for(state="visible")
                page.wait_for_function("() => document.querySelector('[name=revision]').value === '1'")
                self.assertEqual(seen_origins, [self.origin])
                self.assertEqual(self.application.state.store.config()[1]["vaults"][0]["name"], "llm")
                page.locator('[name="vault_name"]').fill(" Invalid intermediate ")
                page.locator('[name="vault_label"]').fill("")
                page.get_by_role("button", name="Konfiguration speichern", exact=True).click()
                page.wait_for_function("() => document.querySelector('#save-status').classList.contains('error')")
                self.assertEqual(page.locator('[name="vault_name"]').input_value(), " Invalid intermediate ")
                self.assertEqual(page.locator('[name="vault_label"]').input_value(), "")
                page.locator('[name="vault_name"]').fill("llm")
                page.locator('[name="vault_label"]').fill("Submitted older edit")
                pending = []
                page.route("**/admin/save", lambda route: pending.append(route))
                with page.expect_request("**/admin/save"):
                    page.get_by_role("button", name="Konfiguration speichern", exact=True).click()
                deadline = time.monotonic() + 3
                while not pending and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                self.assertTrue(pending)
                page.locator('[name="vault_label"]').fill("Newer unsaved edit")
                upstream = pending[0].fetch()
                pending[0].fulfill(response=upstream)
                page.wait_for_function("() => document.querySelector('[name=revision]').value === '2'")
                self.assertEqual(page.locator('[name="vault_label"]').input_value(), "Newer unsaved edit")
                self.assertIn("Neuere Eingaben", page.locator('#save-status').inner_text())
                self.assertEqual(self.application.state.store.config()[1]["vaults"][0]["label"], "Submitted older edit")
                # Copying must not submit or discard newer unsaved vault edits.
                context.grant_permissions(["clipboard-read", "clipboard-write"])
                page.get_by_role("button", name="Befehl kopieren", exact=True).click()
                page.wait_for_function("() => document.querySelector('#copy-status').textContent.startsWith('Kopiert.')")
                self.assertEqual(page.evaluate("navigator.clipboard.readText()"), page.locator('#apply-command').input_value())
                page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw new Error('denied')}}})")
                page.get_by_role("button", name="Befehl kopieren", exact=True).click()
                page.wait_for_function("() => document.querySelector('#copy-status').textContent.includes('manuell')")
                self.assertTrue(page.evaluate("() => {const f=document.querySelector('#apply-command');return document.activeElement===f && f.selectionStart===0 && f.selectionEnd===f.value.length}"))
                self.assertEqual(page.locator('[name="vault_label"]').input_value(), "Newer unsaved edit")
                self.assertEqual(self.application.state.store.config()[0], 2)
                page.set_viewport_size({"width": 390, "height": 844})
                self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > innerWidth"))
                self.assertEqual(failures, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
