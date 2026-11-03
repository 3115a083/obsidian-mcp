# Security policy

This is public source code for a privately operated, read-only Obsidian integration. Report issues privately to the repository owner. Do not include credentials, vault contents or unredacted logs in issues or pull requests.

## Trust boundaries

- Pangolin protects the public resource. The app does not disable or reconfigure it.
- Browser administration requires the allowlisted numeric GitHub account ID.
- MCP requests require either the central GitHub OAuth flow or an expiring, explicitly scoped app capability token.
- The optional STDIO bridge supplies a separate Pangolin resource credential. Run it only inside the operator's trust boundary or behind a correctly associated private Secure MCP Tunnel.
- Each vault worker mounts one selected directory read-only and accepts only its own internal credential. Workers share an internal Docker backplane. This is filesystem and credential separation, not a claim of one isolated network per vault.
- The app has no vault mount and no Docker socket. It can write its state and the explicitly mounted local Compose override. Treat administration as a server-management privilege: that file takes effect when the operator deploys it.

Host/Docker administrators and a compromised application gateway are trusted with the configured vault access. Container isolation does not protect against a host or kernel compromise. A malicious authorized note is data, not an instruction to alter access controls.

## Credentials and revocation

Keep `.env`, `data/master.key`, `data/state.sqlite3`, encrypted OAuth state, generated overrides and bridge credentials out of Git. Capability tokens are stored as SHA-256 hashes; raw values appear only once. Upstream OAuth state is encrypted with a separately derived key. Session signing uses another derivation.

Revoke an individual app capability in the GUI and its Pangolin credential in Pangolin. GitHub OAuth revocation does not revoke independently issued app capability tokens. Browser sessions expire within one hour. Stop the resource or stack for an immediate broad shutdown. Protect and back up state and master key together; losing the key invalidates sessions/OAuth state and worker credentials. Never regenerate it as an error fallback.

## Automated checks

CI runs pinned CodeQL Python analysis, full reachable-history Gitleaks scans, unit and real-browser tests, a real Docker/worker/Nginx test, pip-audit, Bandit, image vulnerability scans and secret scans. The weekly schedule rescans current main, rebuilds candidate images, and separately checks both published private stable images with read-only registry permissions. A passing rebuilt gateway is not evidence that an older deployed image is patched. Files alone do not prove successful runs. Dependabot proposes reviewed dependency and Action updates; hash locks must be regenerated and checked when needed.

Four precise Bandit heuristic dispositions are documented inline, not global rule exclusions: the internal worker's listener, its isolated tmpfs/HOME declarations, and the public OAuth endpoint/auth-method identifier. None is an embedded credential or a host temporary-file operation. Deployment tests enforce that workers publish no ports. Changes to these boundaries require fresh review; do not add blanket suppressions.

## Repository controls

On 2026-11-03 the owner made the source repository public. Internal project records remain private. The initial Rulesets API returned an empty list. During the task an active Main ruleset appeared, requiring CODEOWNERS review, resolved conversations, linear history and CodeQL results, with force pushes/deletion blocked and no bypass actors. It is preserved. The connector could not inspect classic branch protection or change administrator/security settings. The active ruleset was verified through its API. Secret-scanning settings and workflow approval policy remain unverified.

The importable main ruleset requires pull requests, strict GitHub Actions checks (verify, browser, containers, history-secrets and codeql), resolved review threads and blocks force pushes/deletion. It has no bypass actors. Zero independent approvals is intentional for a sole-owner repository; a trusted second reviewer is needed before requiring independent approval. Import the template only as an additional ruleset. It does not replace the existing Main ruleset or relax its CODEOWNERS/CodeQL requirements, and does not enforce anything until activated by an administrator.

The public source contains generic deployment examples. Public GitHub source and GHCR package visibility are separate. Do not remove Docker authentication until an anonymous pull of the actual published images has succeeded. Do not publish runtime state, OAuth secrets, bridge credentials or vault notes to make installation easier.

Report suspected credentials privately. If any real credential was published in Git history or an image, revoke/rotate it at its issuer; removing a line or making a repository private does not revoke a leaked credential. A clean scanner result covers recognized patterns and is not proof that all sensitive data is absent.

No production migration or live Pangolin/GitHub/OpenAI-tunnel verification is asserted by this file.
