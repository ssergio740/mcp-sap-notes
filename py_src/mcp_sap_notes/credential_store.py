from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 86400  # 24 hours


class SapCredentialStore:
    """Encrypted SAP credential store keyed by Microsoft user email."""

    def __init__(
        self,
        path: str | None = None,
        encryption_key: str | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._path = Path(path or os.environ.get("SAP_CRED_STORE_PATH", "sap_credentials.json"))
        self._lock = threading.Lock()

        key_str = encryption_key or os.environ.get("SAP_CRED_ENCRYPTION_KEY", "")
        if key_str:
            try:
                self._fernet = Fernet(key_str.encode() if isinstance(key_str, str) else key_str)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"SAP_CRED_ENCRYPTION_KEY is invalid: {exc}. It must be a valid Fernet key."
                ) from exc
        else:
            generated = Fernet.generate_key()
            self._fernet = Fernet(generated)
            logger.warning(
                "SAP_CRED_ENCRYPTION_KEY not set - generated a temporary key: %s",
                generated.decode(),
            )

    def exists(self, email: str) -> bool:
        return self.get(email) is not None

    def get(self, email: str) -> tuple[str, str] | None:
        data = self._load()
        entry = data.get("users", {}).get(email.lower().strip())
        if entry is None:
            return None

        # Support both old format (plain blob string) and new format (dict with blob + created_at)
        if isinstance(entry, dict):
            blob = entry.get("blob", "")
            created_at = entry.get("created_at", 0)
            age = time.time() - created_at
            if age > self._ttl_seconds:
                logger.info("SAP credentials expired for <%s> (age=%.0fs)", email, age)
                self.delete(email)
                return None
        else:
            blob = entry

        try:
            raw = self._fernet.decrypt(blob.encode())
            creds = json.loads(raw)
            return creds["username"], creds["password"]
        except (InvalidToken, KeyError, json.JSONDecodeError) as exc:
            logger.error("Error decrypting credentials for %s: %s", email, exc)
            return None

    def set(self, email: str, username: str, password: str) -> None:
        email = email.lower().strip()
        raw = json.dumps({"username": username, "password": password}).encode()
        blob = self._fernet.encrypt(raw).decode()
        entry = {"blob": blob, "created_at": time.time()}
        with self._lock:
            data = self._load()
            data.setdefault("users", {})[email] = entry
            self._save(data)
        logger.info("SAP credentials stored for <%s>", email)

    def delete(self, email: str) -> None:
        email = email.lower().strip()
        with self._lock:
            data = self._load()
            if email in data.get("users", {}):
                del data["users"][email]
                self._save(data)
                logger.info("SAP credentials deleted for <%s>", email)

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {"users": {}}
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in %s: %s - starting empty", self._path, exc)
            return {"users": {}}

    def _save(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error writing %s: %s", self._path, exc)
            tmp.unlink(missing_ok=True)
            raise
