# Obsidian MCP

Private, read-only Obsidian integration with one GitHub login, a configuration GUI and separate vault workers. Built for a Linux Docker host such as TrueNAS with Newt in host networking.

**Version 2.0.0 is released. Source code is public; running vaults and credentials remain private.** Local tests do not establish that your Pangolin, GitHub account, private registry or OpenAI tunnel is connected.

## What changes in version 2

- One GitHub OAuth App for the whole administration interface and central MCP authority.
- One MCP endpoint, `/mcp`. Client tokens select the permitted vaults; new shares require no new OAuth App.
- A GUI for adding, removing and retargeting vault shares. Workers mount only their selected directory, read-only.
- A Pangolin-aware STDIO bridge. It sends both Pangolin access-token headers before the request reaches Pangolin and supplies an independently scoped app token.
- Private prebuilt GHCR app and gateway images. Server updates pull images; no local Python/Docker rebuild is required.
- Locked dependency hashes, pinned Actions/base images, tests and regular security scans.

The app never configures Pangolin or starts Docker containers itself. Saving generates a local Compose override; apply it from Dockge. The app has no Docker socket.

## First installation

1. Review the source and select a successfully published image tag. Public source does not make a running vault public. Keep Pangolin authentication and application authorization enabled.
2. Clone this public repository onto the Docker host over HTTPS. No Git credential is needed to read it. Runtime image visibility is configured independently in GHCR; public source does not grant permission to pull a private package.
3. Copy `.env.example` to a local `.env` in Dockge. Set the real HTTPS `PUBLIC_URL`, the numeric `GITHUB_OWNER_ID`, and your host's `VAULT_PARENT`. Supply credentials locally, never in Git or chat.
4. Create **one GitHub OAuth App**. Register these callback URLs on the same App:
   - `https://YOUR_HOST/auth/callback` for browser login.
   - `https://YOUR_HOST/auth/mcp/callback` for clients using central MCP OAuth.
   Register both as exact callback URLs with wildcard matching disabled. GitHub supports [multiple OAuth App callbacks](https://github.blog/changelog/2026-08-14-multiple-redirect-uris-and-token-refresh-for-oauth-apps/). Enter its Client ID and Client Secret in Dockge's `.env`. No GitHub repository or profile-write scopes are requested. Device Flow is not needed.
5. Prepare the private state folder and initially empty Compose override once:

   ```bash
   sudo python3 scripts/prepare.py
   ```

   Default container UID/GID are 568. If changing them, pass `MCP_UID`/`MCP_GID` to the preparation command too. TrueNAS ACLs must permit each worker to traverse/read its selected vault directory. Do not grant blanket write access.
6. Authenticate the **Docker client that performs pulls** to private GHCR with a locally entered, expiring credential with `read:packages`. For an interactive host client:

   ```bash
   sudo docker login ghcr.io --username YOUR_GITHUB_LOGIN
   ```

   Enter the token at the password prompt. A host login does not automatically authenticate the Docker CLI inside Dockge. Dockge needs its own persistent, protected Docker configuration or credential helper. Do not mount these registry credentials into this app or its workers. The exact configuration depends on your Dockge installation and remains an operator setup step.
7. In Dockge pull and deploy. The base Compose file automatically merges local `compose.override.yaml`. Both files must be in the stack directory. Use a free gateway port; the default is bound to `127.0.0.1:3061`.

## Pangolin stays protected

Newt stays in TrueNAS host networking. The Pangolin resource points to **HTTP `127.0.0.1:3061`**, with the original host and path forwarded. Keep its existing authentication enabled. Route the whole HTTPS host; do not strip `/admin`, `/auth`, `/mcp` or `/.well-known` prefixes.

Open `https://YOUR_HOST/admin/`. Complete Pangolin login, then the one GitHub login. The allowlisted numeric GitHub identity is checked server-side. There is no separate app admin password.

For a programmatic MCP connection create a Pangolin resource access token. The bridge sends:

```text
P-Access-Token-Id: <resource token ID>
P-Access-Token: <resource token secret>
Authorization: Bearer <scoped app token>
```

The first two authenticate to Pangolin; the last authorizes access to selected vaults in this app. Do not confuse these with GitHub OAuth credentials. No credential is embedded in a URL. Redirects are deliberately not followed so headers cannot leak to another origin.

**A normal cloud ChatGPT MCP connection cannot be assumed to send arbitrary Pangolin headers.** Changing the server cannot add a header to a request that has already been rejected by Pangolin. Use the bridge with a compatible local client or a correctly associated private Secure MCP Tunnel. See [the connection guide](docs/CONNECTIONS.md). This is an implemented bridge path, not a claim of live OpenAI account/tunnel availability.

## Add or change vaults

In `/admin/`, choose **Vault hinzufügen** and enter a short name, display label and an existing absolute directory under `VAULT_PARENT`. Save, then have Dockge re-read and deploy the stack including its override. Remove orphaned vault workers there when removing shares. No source-code or GitHub OAuth configuration changes are needed.

The app itself has no vault filesystem mount. Each worker gets one selected directory and its own credential. Workers share a private internal backplane, so this is filesystem/credential isolation rather than separate per-vault networks. Workers publish no host ports.

The GUI preserves invalid/empty edits and newer edits typed during an outstanding save. It uses configuration revisions to reject stale writes. A session-expiry error leaves the draft in the current page; log in in a second tab and retry. Explicitly reload or open the current view when you want to load new saved state.

In **Client-Zugriff begrenzen**, create an expiring token for the selected shares. Copy it once into your local bridge credentials. Tokens are hashed at rest. Revocation applies to the next request. Newly created, retargeted or recreated vault shares do not silently inherit old client grants.

## Updates and rollback

For image-only updates, use Dockge's authenticated image pull and deploy. For changed deployment files, update the private checkout first. A shell update uses:

```bash
git pull --ff-only && sudo docker compose pull && sudo docker compose up -d --remove-orphans
```

There is no `build:` in production Compose. Runtime data, `.env` and generated overrides are untracked and must be preserved. Weekly and manually dispatched runs also scan both already-published private `stable` images, so a clean rebuilt candidate does not hide vulnerable installed releases. Scheduled scans do not silently deploy or merge updates. Dependabot creates reviewable proposals; after dependency changes regenerate and review both hash lockfiles.

Both private packages, `obsidian-mcp` and `obsidian-mcp-gateway`, must be readable by the pulling client. The gateway applies Alpine package updates to its pinned Nginx base at build time, and CI scans the resulting image before publication. These OS updates follow the Alpine repositories rather than a frozen package mirror; the immutable published image is the deployment artifact.

The `stable` tag is an update channel. For a fixed installation or rollback, put a successful immutable `sha-...-run-...` tag or image digest into `MCP_IMAGE` and the matching successful gateway tag into `MCP_GATEWAY_IMAGE`. Back up state and test the restore procedure before a production migration. No actual TrueNAS backup/restore has been performed by this implementation.

See [the migration guide](docs/MIGRATION.md) for existing version-1 stacks.

## Checks and limitations

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_workflows.py
```

The real-browser job additionally installs pinned Playwright's Chromium and runs `RUN_BROWSER_TESTS=1 python -m unittest tests.test_browser -v`. The container job builds the image and tests real app-to-worker reads through Nginx, revocation and read-only mounts. Neither is implied by a local unit-test pass.

Visible UTF-8 Markdown only. Hidden paths, symlinks, special files, binary attachments and arbitrary commands are unavailable. Maximum 2 MiB per note, 500 lines per read and a bounded 5,000-note inventory. Search is literal and returns one match per note. Results indicate pagination/limits. PDFs, images and audio ingestion need explicit later implementations.

LoreMonkey transcripts can be imported as Markdown into a permitted campaign vault. The actual PC-to-server transfer is separate. Selected text is sent to OpenAI when used through ChatGPT. Recording and processing must be agreed with the group. An external memory vault is read on relevant requests; it does not automatically load every note into every chat.

Read [SECURITY.md](SECURITY.md) for boundaries, precise static-analysis dispositions, revocation and unverified repository controls. Internal development records and operator-specific configuration must stay outside this public repository.


## Public repository safeguards

CI runs pinned CodeQL Python analysis and Gitleaks across reachable Git history in addition to file/image scans. The branch-ruleset template at [.github/rulesets/main.json](.github/rulesets/main.json) requires pull requests, up-to-date checks from GitHub Actions, resolved review threads, and blocks force pushes/deletion without bypass actors. Importing and activating it as an additional ruleset is a separate administrator action; committing the JSON does not enforce it. Preserve the existing Main ruleset, including CODEOWNERS and CodeQL requirements.

For an owner-only repository, the template requires zero independent approvals so it does not lock the sole owner out. Human review is still required by this project's process. Add a trusted independent reviewer before raising the enforced approval count. No existing stricter protection should be removed.

Repository administrators should enable secret scanning and push protection, dependency alerts and security updates, read-only default workflow permissions, and approval for all external fork contributors. Do not allow Actions to approve pull requests. GitHub settings must be verified in the administration interface; these documentation statements do not establish active settings.
