from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


AuthMethod = str


@dataclass
class ServerConfig:
    pfx_path: str
    pfx_passphrase: str
    sap_username: str | None
    sap_password: str | None
    sap_cred_store_path: str | None
    sap_cred_encryption_key: str | None
    sap_cred_ttl_seconds: int
    allow_interactive_sap_credentials: bool
    auth_method: AuthMethod
    mfa_timeout: int
    max_jwt_age_h: int
    headful: bool
    log_level: str
    mcp_server_url: str | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_audience: str | None = None
    azure_required_scopes: list[str] | None = None
    allowed_email_domains: list[str] | None = None


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_pfx_path(raw_path: str) -> str:
    if not raw_path:
        return ""

    expanded = os.path.expanduser(raw_path)
    path = Path(expanded)
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


def _validate_sap_auth(sap_username: str | None, sap_password: str | None, pfx_path: str, pfx_passphrase: str) -> None:
    if bool(sap_username) ^ bool(sap_password):
        raise RuntimeError("SAP_USERNAME and SAP_PASSWORD must be set together")

    if bool(pfx_path) ^ bool(pfx_passphrase):
        raise RuntimeError("PFX_PATH and PFX_PASSPHRASE must be set together")


def load_config(http_mode: bool = False) -> ServerConfig:
    sap_username = os.getenv("SAP_USERNAME")
    sap_password = os.getenv("SAP_PASSWORD")
    pfx_path = _resolve_pfx_path(os.getenv("PFX_PATH", ""))
    pfx_passphrase = os.getenv("PFX_PASSPHRASE", "")
    sap_cred_store_path = (os.getenv("SAP_CRED_STORE_PATH") or "").strip() or None
    sap_cred_encryption_key = (os.getenv("SAP_CRED_ENCRYPTION_KEY") or "").strip() or None
    sap_cred_ttl_seconds = int(os.getenv("SAP_CRED_TTL_SECONDS", "86400"))

    _validate_sap_auth(sap_username, sap_password, pfx_path, pfx_passphrase)

    is_docker = (
        os.getenv("DOCKER_ENV") == "true"
        or os.getenv("NODE_ENV") == "production"
        or os.getenv("CI") == "true"
    )

    cfg = ServerConfig(
        pfx_path=pfx_path,
        pfx_passphrase=pfx_passphrase,
        sap_username=sap_username,
        sap_password=sap_password,
        sap_cred_store_path=sap_cred_store_path,
        sap_cred_encryption_key=sap_cred_encryption_key,
        sap_cred_ttl_seconds=sap_cred_ttl_seconds,
        allow_interactive_sap_credentials=not http_mode,
        auth_method=os.getenv("AUTH_METHOD", "auto"),
        mfa_timeout=int(os.getenv("MFA_TIMEOUT", "120000")),
        max_jwt_age_h=int(os.getenv("MAX_JWT_AGE_H", "12")),
        headful=(not is_docker and _as_bool(os.getenv("HEADFUL"), False)),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        mcp_server_url=(os.getenv("MCP_SERVER_URL") or "").strip() or None,
        azure_tenant_id=(os.getenv("AZURE_TENANT_ID") or "").strip() or None,
        azure_client_id=(os.getenv("AZURE_CLIENT_ID") or "").strip() or None,
        azure_client_secret=(os.getenv("AZURE_CLIENT_SECRET") or "").strip() or None,
        azure_audience=(os.getenv("MCP_AUDIENCE") or "").strip() or None,
        azure_required_scopes=[s.strip() for s in os.getenv("AZURE_REQUIRED_SCOPES", "access_as_user").split(",") if s.strip()],
        allowed_email_domains=[d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()],
    )

    if http_mode:
        missing = []
        if not cfg.mcp_server_url:
            missing.append("MCP_SERVER_URL")
        if not cfg.azure_tenant_id:
            missing.append("AZURE_TENANT_ID")
        if not cfg.azure_client_id:
            missing.append("AZURE_CLIENT_ID")
        if not cfg.azure_client_secret:
            missing.append("AZURE_CLIENT_SECRET")

        if missing:
            raise RuntimeError(f"Missing HTTP/OAuth configuration: {', '.join(missing)}")

    return cfg
