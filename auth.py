"""One owner identity and one OAuth issuer, independent from vault processes."""
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.github import GitHubProvider


class OwnerGitHubProvider(GitHubProvider):
    def __init__(self, owner_id, **kwargs):
        self.owner_id = owner_id
        super().__init__(**kwargs)

    async def load_access_token(self, token):
        result = await super().load_access_token(token)
        if result is None or str(result.claims.get("sub", "")) != self.owner_id:
            return None
        return result.model_copy(update={"claims": {**result.claims, "vault_ids": "owner"}})


class ClientTokenVerifier(TokenVerifier):
    def __init__(self, state):
        super().__init__(required_scopes=[])
        self.state = state

    async def verify_token(self, token):
        record = self.state.verify_client(token)
        if not record:
            return None
        return AccessToken(token=token, client_id=record["id"], scopes=[],
                           expires_at=record["expires"], subject=record["id"],
                           claims={"vault_ids": record["vault_ids"]})
