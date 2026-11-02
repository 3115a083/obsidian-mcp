# Version 1 to version 2

This is a proposed migration, not a server-side action already performed. Keep the old deployment available for rollback until testing succeeds.

1. Stop the old MCP stack in Dockge. Ignis and the vault files stay separate.
2. Back up the old stack directory, local `.env`, `vaults.json`, `.secrets` and `state`. Verify recovery into a separate test directory. Do not send this backup through Git or chat.
3. Use a new version-2 stack directory with reviewed code and a successfully published image. Do not overlay its empty sample files on an existing configured stack.
4. Configure one GitHub OAuth App and the new local `.env` as described in README. The app-specific admin password from version 1 is not used.
5. Prepare the new `data/` and `compose.override.yaml`. Keep Pangolin authentication enabled and Newt in host networking. Its upstream remains the loopback gateway port.
6. Log in through Pangolin and GitHub. Recreate the intended shares in the GUI using the original vault directories. No note files need to be moved. Do not grant `Notizen` unless you explicitly intend to share it.
7. Save, deploy with the generated override, and verify read-only access and client scopes with harmless test notes. Old per-vault OAuth paths change to the central `/mcp` endpoint. Issue new scoped app client tokens for bridge connections.
8. Test login, callback, a permitted note, a denied vault, token revocation and an image rollback. Finish the OpenAI tunnel setup only if the account prerequisites are available.
9. After acceptance, revoke superseded GitHub OAuth grants/apps and old MCP connections. Remove old containers through Dockge. Delete old credentials or backups only as a separate deliberate cleanup.

State keys and schemas are intentionally not imported automatically from version 1. Restoring the old image with its old state and configuration is the rollback route before production acceptance. No successful backup restore, live TrueNAS deployment or external account verification is claimed here.
