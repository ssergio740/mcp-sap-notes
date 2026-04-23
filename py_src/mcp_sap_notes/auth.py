from __future__ import annotations

from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
import json
import logging
import sys
import threading
import time

from playwright.sync_api import sync_playwright

from .config import ServerConfig


logger = logging.getLogger(__name__)
TOKEN_CACHE_FILE = "token-cache.json"


@dataclass
class AuthState:
    token: str | None = None
    expires_at: int | None = None
    is_authenticated: bool = False


class SapAuthenticator:
    def __init__(self, config: ServerConfig, token_cache_file: str | None = TOKEN_CACHE_FILE) -> None:
        self._config = config
        self._token_cache_file = token_cache_file
        self._state = AuthState()
        self._lock = threading.RLock()

    def ensure_authenticated(self) -> str:
        with self._lock:
            if self._is_token_valid():
                return self._state.token or ""
            self._authenticate()
            if not self._state.token:
                raise RuntimeError("Authentication finished without a token")
            return self._state.token

    def invalidate_auth(self) -> None:
        with self._lock:
            logger.warning("Invalidating cached SAP authentication")
            self._state = AuthState()
            try:
                if self._token_cache_file:
                    cache_path = Path.cwd() / self._token_cache_file
                    if cache_path.exists():
                        cache_path.unlink()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not remove token cache during invalidation: %s", exc)

    def destroy(self) -> None:
        with self._lock:
            self._state = AuthState()

    def _is_token_valid(self) -> bool:
        if not self._state.token or not self._state.expires_at:
            return False
        return int(time.time() * 1000) < (self._state.expires_at - 5 * 60 * 1000)

    def _resolve_auth_method(self) -> str:
        method = (self._config.auth_method or "auto").strip().lower()

        if method == "password":
            return "password"

        if method == "certificate":
            if not self._config.pfx_path or not self._config.pfx_passphrase:
                raise RuntimeError("Certificate auth selected but PFX_PATH/PFX_PASSPHRASE missing")
            return "certificate"

        if self._config.sap_username and self._config.sap_password:
            return "password"
        if self._config.pfx_path and self._config.pfx_passphrase:
            return "certificate"

        return "password"

    def _resolve_password_credentials(self) -> tuple[str, str]:
        username = (self._config.sap_username or "").strip()
        password = self._config.sap_password or ""

        if username and password:
            return username, password

        if not sys.stdin.isatty():
            raise RuntimeError("SAP_USERNAME/SAP_PASSWORD are not configured and no interactive terminal is available")

        if not username:
            username = input("SAP username/email: ").strip()
        if not password:
            password = getpass("SAP password: ")

        if not username or not password:
            raise RuntimeError("SAP username and password are required to continue authentication")

        return username, password

    def _authenticate(self) -> None:
        cached = self._load_cached_token()
        if cached and self._is_cached_token_valid(cached):
            logger.info("Using cached SAP auth token")
            self._state = AuthState(
                token=cached.get("access_token"),
                expires_at=cached.get("expiresAt"),
                is_authenticated=True,
            )
            return

        method = self._resolve_auth_method()
        headless = not self._config.headful

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
            )

            context_kwargs: dict = {
                "ignore_https_errors": True,
                "locale": "en-US",
                "viewport": {"width": 1280, "height": 720},
            }

            if method == "certificate":
                context_kwargs["client_certificates"] = [
                    {
                        "origin": "https://accounts.sap.com",
                        "pfxPath": self._config.pfx_path,
                        "passphrase": self._config.pfx_passphrase,
                    }
                ]

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            if method == "password":
                self._authenticate_with_password(page)
            else:
                self._authenticate_with_certificate(page)

            page.wait_for_timeout(1500)
            cookies = context.cookies()
            if not cookies:
                browser.close()
                raise RuntimeError("Authentication ended with no cookies")

            cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            expires_at = int(time.time() * 1000) + (self._config.max_jwt_age_h * 60 * 60 * 1000)

            self._state = AuthState(token=cookie_string, expires_at=expires_at, is_authenticated=True)
            self._save_cached_token({"access_token": cookie_string, "cookies": cookies, "expiresAt": expires_at})

            browser.close()

    def _is_on_auth_page(self, url: str, title: str) -> bool:
        url_l = url.lower()
        title_l = title.lower()
        return (
            "accounts.sap.com" in url_l
            or "login" in url_l
            or "auth" in url_l
            or "saml2/idp" in url_l
            or "two-factor" in url_l
            or "sign in" in title_l
            or "authentication" in title_l
            or "verify" in title_l
        )

    def _wait_for_auth_complete(self, page, timeout_ms: int) -> None:
        try:
            page.wait_for_url(
                lambda u: all(part not in u.lower() for part in ["accounts.sap.com", "saml2/idp", "login", "two-factor"]),
                timeout=timeout_ms,
            )
        except Exception:
            logger.warning("Auth redirect timeout reached; continuing with cookie inspection")

    def _authenticate_with_certificate(self, page) -> None:
        page.goto("https://me.sap.com/home", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        if self._is_on_auth_page(page.url, page.title()):
            self._wait_for_auth_complete(page, self._config.mfa_timeout)

    def _authenticate_with_password(self, page) -> None:
        page.goto("https://me.sap.com/home", wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        if not self._is_on_auth_page(page.url, page.title()):
            return

        username_selectors = [
            "#j_username",
            "input[name='j_username']",
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "#logOnFormUsername",
        ]
        password_selectors = [
            "#j_password",
            "input[name='j_password']",
            "input[name='password']",
            "input[type='password']",
            "#logOnFormPassword",
        ]

        username_field = None
        for selector in username_selectors:
            try:
                username_field = page.wait_for_selector(selector, timeout=3000, state="visible")
                if username_field:
                    break
            except Exception:
                continue
        if not username_field:
            raise RuntimeError("Could not find SAP username field")

        username = (self._config.sap_username or "").strip()
        password = self._config.sap_password or ""

        if not username or not password:
            if self._config.allow_interactive_sap_credentials and sys.stdin.isatty():
                username, password = self._resolve_password_credentials()
            else:
                raise RuntimeError(
                    "SAP_USERNAME/SAP_PASSWORD are required in HTTP/AWS mode. Set them as container environment variables or AWS secrets."
                )

        username_field.click(click_count=3)
        username_field.fill(username)

        password_field = None
        for selector in password_selectors:
            try:
                password_field = page.wait_for_selector(selector, timeout=2000, state="visible")
                if password_field:
                    break
            except Exception:
                continue

        if not password_field:
            for submit_selector in ["button[type='submit']", "input[type='submit']", "#logOnFormSubmit"]:
                try:
                    submit = page.wait_for_selector(submit_selector, timeout=2000, state="visible")
                    if submit:
                        submit.click()
                        break
                except Exception:
                    continue
            page.wait_for_timeout(2000)
            for selector in password_selectors:
                try:
                    password_field = page.wait_for_selector(selector, timeout=10000, state="visible")
                    if password_field:
                        break
                except Exception:
                    continue

        if not password_field:
            raise RuntimeError("Could not find SAP password field")

        password_field.click(click_count=3)
        password_field.fill(password)

        for submit_selector in ["button[type='submit']", "input[type='submit']", "#logOnFormSubmit"]:
            try:
                submit = page.wait_for_selector(submit_selector, timeout=2000, state="visible")
                if submit:
                    submit.click()
                    break
            except Exception:
                continue

        page.wait_for_timeout(3000)
        if self._is_on_auth_page(page.url, page.title()):
            self._wait_for_auth_complete(page, self._config.mfa_timeout)

    def _load_cached_token(self) -> dict | None:
        if not self._token_cache_file:
            return None

        path = Path.cwd() / self._token_cache_file
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("access_token"), str) and isinstance(data.get("expiresAt"), int):
                return data
        except Exception:
            logger.warning("Token cache is invalid and will be ignored")
        return None

    def _is_cached_token_valid(self, token_data: dict) -> bool:
        expires_at = int(token_data.get("expiresAt", 0))
        return int(time.time() * 1000) < (expires_at - 5 * 60 * 1000)

    def _save_cached_token(self, token_data: dict) -> None:
        if not self._token_cache_file:
            return

        try:
            (Path.cwd() / self._token_cache_file).write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist token cache: %s", exc)


def validate_sap_credentials(username: str, password: str, *, headful: bool = False) -> None:
    from .config import ServerConfig

    temp_config = ServerConfig(
        pfx_path="",
        pfx_passphrase="",
        sap_username=username,
        sap_password=password,
        sap_cred_store_path=None,
        sap_cred_encryption_key=None,
        sap_cred_ttl_seconds=86400,
        allow_interactive_sap_credentials=False,
        auth_method="password",
        mfa_timeout=120000,
        max_jwt_age_h=12,
        headful=headful,
        log_level="INFO",
        mcp_server_url=None,
        azure_tenant_id=None,
        azure_client_id=None,
        azure_client_secret=None,
        azure_audience=None,
        azure_required_scopes=None,
        allowed_email_domains=None,
    )

    SapAuthenticator(temp_config, token_cache_file=None).ensure_authenticated()
