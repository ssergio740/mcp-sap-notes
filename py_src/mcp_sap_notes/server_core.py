from __future__ import annotations

import dataclasses
import logging
import threading
from typing import Callable, TypeVar

from fastmcp import FastMCP

from .auth import SapAuthenticator
from .config import ServerConfig
from .html_utils import parse_note_content
from .sap_notes_api import SapNotesApiClient


logger = logging.getLogger(__name__)


def _current_user_email() -> str | None:
    """Return the email of the currently authenticated user, if any."""
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
        token = get_access_token()
        if token and token.claims:
            upstream = token.claims.get("upstream_claims") or {}
            return upstream.get("email")
    except Exception:
        pass
    return None

SAP_NOTE_SEARCH_DESCRIPTION = (
    "Search the SAP Knowledge Base for SAP Notes — official articles documenting bugs, fixes, patches, "
    "corrections, security vulnerabilities, and known issues."
)

SAP_NOTE_GET_DESCRIPTION = (
    "Fetch the complete content and metadata of a specific SAP Note by its ID. "
    "Set includeCorrections=true to fetch detailed correction instructions."
)

T = TypeVar("T")


def _build_fetch_text(output: dict) -> str:
    text = f"**SAP Note {output['id']} - {output['title']}**\n\n"
    text += f"Component: {output.get('componentText') or output.get('component') or 'Not specified'} | "
    text += f"Priority: {output.get('priority') or 'Not specified'} | "
    text += f"Category: {output.get('category') or 'Not specified'} | "
    text += f"Released: {output.get('releaseDate')}"
    if output.get("version"):
        text += f" | Version: {output['version']}"
    text += f"\nURL: {output.get('url')}\n\n"
    text += f"{output.get('content', '')}\n"

    if output.get("validity"):
        validity = ", ".join(
            f"{v.get('softwareComponent')} {v.get('versionFrom')}-{v.get('versionTo')}" for v in output["validity"]
        )
        text += f"\n**Validity:** {validity}\n"

    if output.get("correctionsInfo"):
        ci = output["correctionsInfo"]
        text += (
            f"\n**Corrections:** {ci.get('totalCorrections', '?')} corrections, "
            f"{ci.get('totalManualActivities', 0)} manual activities, "
            f"{ci.get('totalPrerequisites', 0)} prerequisites\n"
        )

    if output.get("prerequisites"):
        pre = ", ".join(f"Note {p.get('noteNumber')}" for p in output["prerequisites"])
        text += f"\n**Prerequisites:** {pre}\n"

    if output.get("correctionDetails"):
        text += f"\n**Correction Details ({len(output['correctionDetails'])} entries):**\n"
        for cd in output["correctionDetails"]:
            text += f"  - {cd.get('softwareComponent')} {cd.get('versionFrom')}-{cd.get('versionTo')}"
            objects = cd.get("objects") or []
            if objects:
                sample = ", ".join(f"{o.get('objectType')} {o.get('objectName')}" for o in objects[:3])
                suffix = "..." if len(objects) > 3 else ""
                text += f" - {len(objects)} objects ({sample}{suffix})"
            text += "\n"

    return text


def build_mcp_server(config: ServerConfig, sap_store=None) -> FastMCP:
    mcp = FastMCP("sap-note-search-mcp")
    authenticator = SapAuthenticator(config)
    client = SapNotesApiClient(config)

    # Per-user authenticators keyed by email (HTTP/OAuth mode only)
    _user_authenticators: dict[str, SapAuthenticator] = {}
    _user_auth_lock = threading.Lock()

    def _get_authenticator() -> SapAuthenticator:
        if sap_store is None:
            return authenticator
        email = _current_user_email()
        if not email:
            return authenticator
        with _user_auth_lock:
            if email not in _user_authenticators:
                creds = sap_store.get(email)
                if not creds:
                    raise RuntimeError(
                        f"No SAP credentials registered for <{email}>. "
                        "Please complete the SAP registration flow."
                    )
                user_config = dataclasses.replace(config, sap_username=creds[0], sap_password=creds[1])
                _user_authenticators[email] = SapAuthenticator(user_config, token_cache_file=None)
            return _user_authenticators[email]

    def with_auth_retry(fn: Callable[[str], T]) -> T:
        auth = _get_authenticator()
        token = auth.ensure_authenticated()
        try:
            return fn(token)
        except Exception as error:  # noqa: BLE001
            msg = str(error)
            if any(k in msg for k in ("SESSION_EXPIRED", "401", "Unauthorized", "session expired")):
                auth.invalidate_auth()
                new_token = auth.ensure_authenticated()
                return fn(new_token)
            raise

    @mcp.tool(name="search", description=SAP_NOTE_SEARCH_DESCRIPTION)
    def search(q: str, lang: str = "EN") -> dict:
        if len(q.strip()) < 2:
            return {"content": [{"type": "text", "text": "Search failed: query must be at least 2 characters"}], "isError": True}
        if lang not in {"EN", "DE"}:
            return {"content": [{"type": "text", "text": "Search failed: lang must be EN or DE"}], "isError": True}

        try:
            search_response = with_auth_retry(lambda token: client.search_notes(q, token, 10))
            output = {
                "totalResults": search_response["totalResults"],
                "query": search_response["query"],
                "results": [
                    {
                        "id": note.get("id"),
                        "title": note.get("title"),
                        "summary": note.get("summary"),
                        "component": note.get("component"),
                        "releaseDate": note.get("releaseDate"),
                        "language": note.get("language"),
                        "url": note.get("url"),
                    }
                    for note in search_response.get("results", [])
                ],
            }

            text = f"Found {output['totalResults']} SAP Note(s) for query: \"{output['query']}\"\n\n"
            for note in output["results"]:
                text += f"**SAP Note {note['id']}**\n"
                text += f"Title: {note['title']}\n"
                text += f"Summary: {note['summary']}\n"
                text += f"Component: {note.get('component') or 'Not specified'}\n"
                text += f"Release Date: {note.get('releaseDate')}\n"
                text += f"Language: {note.get('language')}\n"
                text += f"URL: {note.get('url')}\n\n"

            return {
                "content": [{"type": "text", "text": text}],
                "structuredContent": output,
            }
        except Exception as error:  # noqa: BLE001
            logger.exception("Search failed")
            return {
                "content": [{"type": "text", "text": f"Search failed: {error}"}],
                "isError": True,
            }

    @mcp.tool(name="fetch", description=SAP_NOTE_GET_DESCRIPTION)
    def fetch(id: str, lang: str = "EN", includeCorrections: bool = False) -> dict:  # noqa: N803
        if not id.strip():
            return {"content": [{"type": "text", "text": "Failed to retrieve SAP Note: id cannot be empty"}], "isError": True}
        if lang not in {"EN", "DE"}:
            return {"content": [{"type": "text", "text": "Failed to retrieve SAP Note: lang must be EN or DE"}], "isError": True}

        try:
            note_detail = with_auth_retry(lambda token: client.get_note(id, token))
            if not note_detail:
                return {
                    "content": [{"type": "text", "text": f"SAP Note {id} not found or not accessible."}],
                    "isError": True,
                }

            if includeCorrections and note_detail.get("correctionsSummary"):
                try:
                    corrections = with_auth_retry(
                        lambda token: client.get_correction_details(id, note_detail.get("correctionsSummary", []), token)
                    )
                    if corrections:
                        note_detail["correctionDetails"] = corrections
                except Exception as corr_error:  # noqa: BLE001
                    logger.warning("Correction details fetch failed (non-fatal): %s", corr_error)

            parsed = parse_note_content(note_detail.get("content") or "")
            output = {
                "id": note_detail.get("id"),
                "title": note_detail.get("title"),
                "summary": note_detail.get("summary"),
                "component": note_detail.get("component"),
                "componentText": note_detail.get("componentText"),
                "priority": note_detail.get("priority"),
                "category": note_detail.get("category"),
                "version": str(note_detail.get("version")) if note_detail.get("version") is not None else None,
                "status": note_detail.get("status"),
                "releaseDate": note_detail.get("releaseDate"),
                "language": note_detail.get("language"),
                "url": note_detail.get("url"),
                "content": parsed.get("plainText") or note_detail.get("content"),
            }

            for field in (
                "validity",
                "supportPackages",
                "supportPackagePatches",
                "references",
                "prerequisites",
                "sideEffects",
                "correctionsInfo",
                "correctionsSummary",
                "correctionDetails",
                "manualActions",
                "attachments",
                "downloadUrl",
            ):
                value = note_detail.get(field)
                if value:
                    output[field] = value

            return {
                "content": [{"type": "text", "text": _build_fetch_text(output)}],
                "structuredContent": output,
            }
        except Exception as error:  # noqa: BLE001
            logger.exception("Note retrieval failed")
            return {
                "content": [{"type": "text", "text": f"Failed to retrieve SAP Note {id}: {error}"}],
                "isError": True,
            }

    return mcp
