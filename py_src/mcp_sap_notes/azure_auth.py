from __future__ import annotations

import logging

from mcp.server.auth.provider import TokenError
from fastmcp.server.auth.providers.azure import AzureProvider


logger = logging.getLogger(__name__)


class DomainFilteredAzureProvider(AzureProvider):
    """Azure OAuth provider with domain allowlist enforcement."""

    _MULTI_TENANT = {"common", "organizations", "consumers"}

    def __init__(
        self,
        *,
        allowed_domains: list[str],
        tenant_id: str,
        **kwargs,
    ) -> None:
        super().__init__(tenant_id=tenant_id, **kwargs)
        self._allowed_domains = {d.lower().strip() for d in allowed_domains if d.strip()}

        if tenant_id in self._MULTI_TENANT:
            self._token_validator.issuer = None

    async def _extract_upstream_claims(self, idp_tokens: dict) -> dict | None:
        claims = await super()._extract_upstream_claims(idp_tokens)
        if not claims:
            raise TokenError("access_denied", "Could not extract identity claims from Microsoft token")

        email = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
            or claims.get("unique_name")
        )

        if not email:
            raise TokenError("access_denied", "Microsoft token does not contain an email identity claim")

        normalized_email = str(email).strip().lower()
        if "@" not in normalized_email:
            raise TokenError("access_denied", "Identity claim does not contain a valid email")

        domain = normalized_email.rsplit("@", 1)[1]

        if not self._allowed_domains:
            raise TokenError("server_error", "Allowed domain list is empty")

        allowed = any(domain == candidate or domain.endswith(f".{candidate}") for candidate in self._allowed_domains)
        if not allowed:
            logger.warning("OAuth access denied for email <%s>", normalized_email)
            raise TokenError("access_denied", f"Email domain {domain} is not allowed")

        logger.info("OAuth login accepted for <%s>", normalized_email)
        return claims
