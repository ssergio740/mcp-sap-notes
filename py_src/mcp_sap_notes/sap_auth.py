from __future__ import annotations

import asyncio
import html as html_lib
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastmcp.server.auth.providers.azure import AzureProvider
from mcp.server.auth.provider import TokenError
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from .auth import validate_sap_credentials
from .credential_store import SapCredentialStore

logger = logging.getLogger(__name__)


class SapGatedAzureProvider(AzureProvider):
    """Azure OAuth provider that delegates access to per-user SAP credentials."""

    _MULTI_TENANT = {"common", "organizations", "consumers"}

    def __init__(
        self,
        *,
        tenant_id: str,
        sap_store: SapCredentialStore,
        **kwargs: Any,
    ) -> None:
        super().__init__(tenant_id=tenant_id, **kwargs)
        self._sap_store = sap_store
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_lock = asyncio.Lock()

        if tenant_id in self._MULTI_TENANT:
            self._token_validator.issuer = None

    async def _extract_upstream_claims(self, idp_tokens: dict) -> dict | None:
        claims = await super()._extract_upstream_claims(idp_tokens)
        if not claims:
            raise TokenError(
                "access_denied",
                "No se pudieron extraer los datos de identidad del token de Microsoft",
            )

        email: str | None = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
            or claims.get("unique_name")
        )

        if not email:
            raise TokenError(
                "access_denied",
                "El token de Microsoft no contiene un claim de correo electrónico",
            )

        claims["email"] = email.lower().strip()
        logger.info("Login de Microsoft aceptado: <%s>", claims["email"])
        return claims

    async def _handle_idp_callback(self, request: Request) -> HTMLResponse | RedirectResponse:
        from fastmcp.server.auth.oauth_proxy.proxy import ClientCode, DEFAULT_AUTH_CODE_EXPIRY_SECONDS
        from fastmcp.server.auth.oauth_proxy.ui import create_error_html

        try:
            idp_code = request.query_params.get("code")
            txn_id = request.query_params.get("state")
            error = request.query_params.get("error")

            if error:
                error_description = request.query_params.get("error_description")
                logger.error("IdP callback error: %s - %s", error, error_description)
                return HTMLResponse(
                    content=create_error_html(
                        error_title="OAuth Error",
                        error_message=f"Authentication failed: {error_description or 'Unknown error'}",
                        error_details={"Error Code": error},
                    ),
                    status_code=400,
                )

            if not idp_code or not txn_id:
                logger.error("IdP callback missing code or transaction ID")
                return HTMLResponse(
                    content=create_error_html(
                        error_title="OAuth Error",
                        error_message="Missing authorization code or transaction ID.",
                    ),
                    status_code=400,
                )

            transaction_model = await self._transaction_store.get(key=txn_id)
            if not transaction_model:
                logger.error("IdP callback con transaction ID inválido: %s", txn_id)
                return HTMLResponse(
                    content=create_error_html(
                        error_title="OAuth Error",
                        error_message="Invalid or expired authorization transaction. Please try authenticating again.",
                    ),
                    status_code=400,
                )

            if self._require_authorization_consent is True:
                consent_token = transaction_model.consent_token
                if not consent_token:
                    return HTMLResponse(
                        content=create_error_html(
                            error_title="Authorization Error",
                            error_message="Invalid authorization flow. Please try authenticating again.",
                        ),
                        status_code=403,
                    )
                if not self._verify_consent_binding_cookie(request, txn_id, consent_token):
                    logger.warning("Consent binding cookie inválida para transaction %s", txn_id)
                    return HTMLResponse(
                        content=create_error_html(
                            error_title="Authorization Error",
                            error_message="Authorization session mismatch. Please try authenticating again.",
                        ),
                        status_code=403,
                    )

            transaction = transaction_model.model_dump()
            oauth_client = self._create_upstream_oauth_client()
            try:
                idp_redirect_uri = f"{str(self.base_url).rstrip('/')}{self._redirect_path}"
                token_params: dict[str, Any] = {
                    "url": self._upstream_token_endpoint,
                    "code": idp_code,
                    "redirect_uri": idp_redirect_uri,
                }
                proxy_code_verifier = transaction.get("proxy_code_verifier")
                if proxy_code_verifier:
                    token_params["code_verifier"] = proxy_code_verifier
                exchange_scopes = self._prepare_scopes_for_token_exchange(transaction.get("scopes") or [])
                if exchange_scopes:
                    token_params["scope"] = " ".join(exchange_scopes)
                if self._extra_token_params:
                    token_params.update(self._extra_token_params)

                idp_tokens: dict[str, Any] = await oauth_client.fetch_token(**token_params)
            except Exception as exc:  # noqa: BLE001
                logger.error("IdP token exchange failed: %s", exc)
                return HTMLResponse(
                    content=create_error_html(
                        error_title="OAuth Error",
                        error_message=f"Token exchange with identity provider failed: {exc}",
                    ),
                    status_code=500,
                )

            try:
                claims = await self._extract_upstream_claims(idp_tokens)
            except TokenError as exc:
                return HTMLResponse(
                    content=create_error_html(
                        error_title="Access Denied",
                        error_message=str(exc.error_description),
                    ),
                    status_code=403,
                )

            email: str = claims["email"]

            if self._sap_store.exists(email):
                logger.info("Credenciales SAP encontradas para <%s>, completando OAuth", email)
                response = await self._complete_oauth_flow(
                    idp_tokens,
                    transaction,
                    txn_id,
                    DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
                    ClientCode,
                )
                self._clear_consent_binding_cookie(request, response, txn_id)
                return response

            session_id = secrets.token_urlsafe(32)
            async with self._pending_lock:
                self._pending[session_id] = {
                    "email": email,
                    "idp_tokens": idp_tokens,
                    "transaction": transaction,
                    "txn_id": txn_id,
                    "claims": claims,
                    "expires_at": time.time() + 600,
                }

            logger.info("Sin credenciales SAP para <%s>, redirigiendo a formulario de registro", email)
            register_url = f"{str(self.base_url).rstrip('/')}/auth/sap-register?session={session_id}"
            return RedirectResponse(url=register_url, status_code=302)

        except Exception as exc:  # noqa: BLE001
            logger.error("Error en IdP callback handler: %s", exc, exc_info=True)
            from fastmcp.server.auth.oauth_proxy.ui import create_error_html as _ceh

            return HTMLResponse(
                content=_ceh(
                    error_title="OAuth Error",
                    error_message="Internal server error during OAuth callback. Please try again.",
                ),
                status_code=500,
            )

    async def _complete_oauth_flow(
        self,
        idp_tokens: dict[str, Any],
        transaction: dict[str, Any],
        txn_id: str,
        ttl: int,
        ClientCode: type,
    ) -> RedirectResponse:
        client_code = secrets.token_urlsafe(32)
        code_expires_at = int(time.time() + ttl)

        await self._code_store.put(
            key=client_code,
            value=ClientCode(
                code=client_code,
                client_id=transaction["client_id"],
                redirect_uri=transaction["client_redirect_uri"],
                code_challenge=transaction["code_challenge"],
                code_challenge_method=transaction["code_challenge_method"],
                scopes=transaction["scopes"],
                idp_tokens=idp_tokens,
                expires_at=code_expires_at,
                created_at=time.time(),
            ),
            ttl=ttl,
        )
        await self._transaction_store.delete(key=txn_id)

        client_redirect_uri = transaction["client_redirect_uri"]
        client_state = transaction["client_state"]
        sep = "&" if "?" in client_redirect_uri else "?"
        url = f"{client_redirect_uri}{sep}{urlencode({'code': client_code, 'state': client_state})}"
        return RedirectResponse(url=url, status_code=302)

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        routes.append(
            Route(
                path="/auth/sap-register",
                endpoint=self._sap_register_handler,
                methods=["GET", "POST"],
            )
        )
        return routes

    async def _sap_register_handler(self, request: Request) -> Response:
        if request.method == "GET":
            return await self._sap_register_get(request)
        return await self._sap_register_post(request)

    async def _sap_register_get(self, request: Request) -> Response:
        session_id = request.query_params.get("session", "")
        async with self._pending_lock:
            pending = self._pending.get(session_id)

        if not pending or time.time() > pending["expires_at"]:
            async with self._pending_lock:
                self._pending.pop(session_id, None)
            return HTMLResponse(content=_html_expired(), status_code=400)

        return HTMLResponse(content=_html_form(session_id, pending["email"]), status_code=200)

    async def _sap_register_post(self, request: Request) -> Response:
        from fastmcp.server.auth.oauth_proxy.proxy import ClientCode, DEFAULT_AUTH_CODE_EXPIRY_SECONDS

        session_id = request.query_params.get("session", "")
        form = await request.form()
        sap_username = str(form.get("sap_username", "")).strip()
        sap_password = str(form.get("sap_password", ""))

        async with self._pending_lock:
            pending = self._pending.pop(session_id, None)

        if not pending or time.time() > pending["expires_at"]:
            return HTMLResponse(content=_html_expired(), status_code=400)

        if not sap_username or not sap_password:
            async with self._pending_lock:
                self._pending[session_id] = pending
            return HTMLResponse(
                content=_html_form(session_id, pending["email"], error="El usuario y la contraseña SAP son requeridos."),
                status_code=200,
            )

        try:
            await asyncio.to_thread(
                validate_sap_credentials,
                sap_username,
                sap_password,
                headful=False,
            )
        except Exception as exc:  # noqa: BLE001
            async with self._pending_lock:
                self._pending[session_id] = pending
            return HTMLResponse(
                content=_html_form(
                    session_id,
                    pending["email"],
                    error=f"No se pudo validar SAP: {exc}",
                ),
                status_code=200,
            )

        await asyncio.to_thread(
            self._sap_store.set,
            pending["email"],
            sap_username,
            sap_password,
        )

        return await self._complete_oauth_flow(
            pending["idp_tokens"],
            pending["transaction"],
            pending["txn_id"],
            DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
            ClientCode,
        )


def _html_form(session_id: str, email: str, error: str | None = None) -> str:
    error_block = ""
    if error:
        error_block = f'<div class="error-box">{html_lib.escape(error)}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SAP Login — MCP SAP Notes</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:#f4f5f7;display:flex;align-items:center;justify-content:center;
         min-height:100vh;padding:1rem}}
    .card{{background:#fff;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.12);
           padding:2.5rem;width:100%;max-width:420px}}
    h1{{font-size:1.4rem;color:#1a1a2e;margin-bottom:.4rem}}
    .subtitle{{color:#666;font-size:.9rem;margin-bottom:1.5rem}}
    .email-badge{{background:#e8f4fd;border:1px solid #b3d9f7;border-radius:4px;
                  padding:.5rem .8rem;font-size:.85rem;color:#1a6ca8;margin-bottom:1.5rem}}
    label{{display:block;font-size:.85rem;font-weight:600;color:#333;margin-bottom:.3rem}}
    input[type=text],input[type=password]{{width:100%;padding:.6rem .8rem;
      border:1px solid #d0d5dd;border-radius:6px;font-size:.95rem;margin-bottom:1rem}}
    input:focus{{outline:none;border-color:#0078d4}}
    .error-box{{background:#fff0f0;border:1px solid #ffcccc;border-radius:6px;
                padding:.7rem 1rem;color:#c00;font-size:.88rem;margin-bottom:1rem}}
    button{{width:100%;padding:.75rem;background:#0078d4;color:#fff;border:none;
            border-radius:6px;font-size:1rem;font-weight:600;cursor:pointer}}
    button:hover{{background:#006abd}}
    .note{{font-size:.8rem;color:#888;margin-top:1rem;text-align:center}}
  </style>
</head>
<body>
  <div class="card">
    <h1>SAP System Login</h1>
    <p class="subtitle">Ingresa tus credenciales SAP para continuar con el acceso al MCP server.</p>
    <div class="email-badge">Sesión Microsoft: {html_lib.escape(email)}</div>
    {error_block}
    <form method="POST" action="/auth/sap-register?session={html_lib.escape(session_id)}">
      <label for="sap_username">Usuario SAP</label>
      <input type="text" id="sap_username" name="sap_username"
             autocomplete="username" autocapitalize="off" required>
      <label for="sap_password">Contraseña SAP</label>
      <input type="password" id="sap_password" name="sap_password"
             autocomplete="current-password" required>
      <button type="submit">Conectar a SAP</button>
    </form>
    <p class="note">Tus credenciales se cifran y almacenan de forma segura en el servidor.</p>
  </div>
</body>
</html>"""


def _html_expired() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Sesión expirada — MCP SAP Notes</title>
  <style>
    body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
         min-height:100vh;background:#f4f5f7}}
    .card{{background:#fff;border-radius:8px;padding:2rem;
           box-shadow:0 2px 12px rgba(0,0,0,.12);max-width:400px;text-align:center}}
    h1{{color:#c00;margin-bottom:1rem}}
    a{{color:#0078d4}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Sesión expirada</h1>
    <p>La sesión de registro expiró (límite de 10 minutos).</p>
    <p style="margin-top:1rem">
      Por favor vuelve a iniciar sesión con Microsoft para reiniciar el proceso.
    </p>
  </div>
</body>
</html>"""
