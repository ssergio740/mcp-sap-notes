from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from .credential_store import SapCredentialStore
from .config import load_config
from .server_core import build_mcp_server
from .sap_auth import SapGatedAzureProvider


logger = logging.getLogger(__name__)


def _build_auth(config, sap_store=None):
    required_scopes = config.azure_required_scopes or ["access_as_user"]
    if sap_store is None:
        sap_store = SapCredentialStore(
            path=config.sap_cred_store_path,
            encryption_key=config.sap_cred_encryption_key,
        )

    return SapGatedAzureProvider(
        client_id=config.azure_client_id,
        client_secret=config.azure_client_secret,
        tenant_id=config.azure_tenant_id,
        required_scopes=required_scopes,
        base_url=(config.mcp_server_url or "").rstrip("/"),
        require_authorization_consent="external",
        sap_store=sap_store,
    )


def main() -> None:
    load_dotenv()

    config = load_config(http_mode=True)
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))

    sap_store = SapCredentialStore(
        path=config.sap_cred_store_path,
        encryption_key=config.sap_cred_encryption_key,
        ttl_seconds=config.sap_cred_ttl_seconds,
    )
    mcp = build_mcp_server(config, sap_store=sap_store)
    mcp.auth = _build_auth(config, sap_store=sap_store)

    host = os.getenv("HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("HTTP_PORT", "8090"))
    path = os.getenv("MCP_HTTP_PATH", "/mcp")

    logger.info("Starting FastMCP HTTP server on http://%s:%s%s", host, port, path)
    mcp.run(transport="http", host=host, port=port, path=path)


if __name__ == "__main__":
    main()
