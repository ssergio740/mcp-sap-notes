from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from .config import ServerConfig


logger = logging.getLogger(__name__)


class SapNotesApiClient:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._raw_notes_url = "https://me.sap.com/backend/raw/sapnotes"
        self._coveo_search_url = "https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2"
        self._coveo_org_id = "sapamericaproductiontyfzmfz0"
        self._coveo_token_cache: dict[str, object] | None = None

    def search_notes(self, query: str, token: str, max_results: int = 10) -> dict:
        coveo_token = self._get_coveo_token(token)
        search_url = f"{self._coveo_search_url}?organizationId={self._coveo_org_id}"
        response = requests.post(
            search_url,
            headers={
                "authorization": f"Bearer {coveo_token}",
                "content-type": "application/json",
                "cookie": self._format_cookie_header(token),
                "origin": "https://me.sap.com",
                "referer": "https://me.sap.com/",
            },
            data=json.dumps(self._build_coveo_search_body(query, max_results)),
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        results = self._parse_coveo_response(data)

        if not results and re.fullmatch(r"\d{5,10}", query.strip()):
            note = self.get_note(query.strip(), token)
            if note:
                results = [
                    {
                        "id": note["id"],
                        "title": note["title"],
                        "summary": note["summary"],
                        "component": note.get("component"),
                        "releaseDate": note["releaseDate"],
                        "language": note["language"],
                        "url": note["url"],
                    }
                ]

        return {
            "results": results,
            "totalResults": data.get("totalCount", len(results)),
            "query": query,
        }

    def get_note(self, note_id: str, token: str) -> dict | None:
        note = self._get_note_with_playwright(note_id, token)
        if note:
            return note

        response = requests.get(
            f"{self._raw_notes_url}/Detail?q={note_id}&t=E&isVTEnabled=false",
            headers={
                "cookie": self._format_cookie_header(token),
                "accept": "application/json,text/html,*/*",
                "referer": "https://me.sap.com/",
            },
            timeout=30,
            allow_redirects=True,
        )

        if response.status_code == 404:
            return None

        if not response.ok:
            response.raise_for_status()

        return self._parse_raw_note_response(response.text, note_id)

    def get_correction_details(self, note_id: str, corrections_summary: list[dict], token: str) -> list[dict]:
        padded = note_id.zfill(10)
        results: list[dict] = []

        for summary in corrections_summary:
            pak_id = summary.get("pakId")
            if not pak_id:
                continue

            corr_set = self._fetch_corrins_set(padded, str(pak_id), token)
            for entry in corr_set:
                correction = {
                    "softwareComponent": entry.get("Name") or summary.get("softwareComponent", ""),
                    "versionFrom": entry.get("VerFrom") or "",
                    "versionTo": entry.get("VerTo") or "",
                    "sapNotesNumber": entry.get("SapNotesNumber") or note_id,
                    "sapNotesTitle": entry.get("SapNotesTitle") or "",
                }

                objects = self._fetch_corrins_navigation(entry, "TADIR", token)
                if objects:
                    correction["objects"] = [
                        {
                            "objectName": obj.get("ObjName", ""),
                            "objectType": obj.get("ObjType", ""),
                        }
                        for obj in objects
                        if obj.get("ObjName")
                    ]

                prerequisites = self._fetch_corrins_navigation(entry, "Prerequisite", token)
                if prerequisites:
                    correction["prerequisites"] = [
                        {
                            "noteNumber": p.get("SapNotesNumber", ""),
                            "title": p.get("Title", ""),
                        }
                        for p in prerequisites
                        if p.get("SapNotesNumber")
                    ]

                results.append(correction)

        return results

    def cleanup(self) -> None:
        return

    def _get_coveo_token(self, sap_token: str) -> str:
        now_ms = int(time.time() * 1000)
        if self._coveo_token_cache and int(self._coveo_token_cache.get("expiresAt", 0)) > now_ms:
            return str(self._coveo_token_cache["token"])

        token = self._get_coveo_token_direct(sap_token)
        self._coveo_token_cache = {
            "token": token,
            "expiresAt": now_ms + 14 * 60 * 1000,
        }
        return token

    def _get_coveo_token_direct(self, sap_token: str) -> str:
        headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "x-requested-with": "XMLHttpRequest",
            "origin": "https://me.sap.com",
            "referer": "https://me.sap.com/",
            "cookie": self._format_cookie_header(sap_token),
        }

        app_response = requests.get(
            "https://me.sap.com/backend/raw/core/Applications/coveo",
            headers=headers,
            timeout=30,
        )
        if not app_response.ok:
            logger.info(
                "Coveo app bootstrap returned %s; continuing with direct token endpoint",
                app_response.status_code,
            )

        token: str | None = None
        token_response = requests.get(
            "https://me.sap.com/backend/raw/coveo/CoveoToken",
            headers=headers,
            timeout=30,
        )
        if token_response.ok:
            try:
                token_data = token_response.json()
            except Exception as error:  # noqa: BLE001
                logger.info("Coveo token endpoint returned non-JSON payload: %s", error)
            else:
                token = token_data.get("token")
        else:
            logger.info(
                "Coveo token endpoint returned %s; trying browser fallback",
                token_response.status_code,
            )

        if not token:
            token = self._get_coveo_token_from_browser(sap_token)

        if not token:
            raise RuntimeError("Coveo token not found")

        return str(token)

    def _get_coveo_token_from_browser(self, sap_token: str) -> str | None:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not self._config.headful,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
            )
            try:
                context = browser.new_context(ignore_https_errors=True, locale="en-US")
                cookies = self._parse_cookies_from_token(self._format_cookie_header(sap_token))
                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception as error:  # noqa: BLE001
                        logger.warning("Could not inject cookies into browser fallback: %s", error)

                page = context.new_page()
                page.goto("https://me.sap.com/search", wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                extracted = page.evaluate(
                    """async () => {
                        const scan = (text) => {
                            if (!text) return null;
                            const patterns = [
                                /(?:coveoToken|bearerToken|accessToken)\s*[:=]\s*["']([^"'\\s]{20,})["']/i,
                                /"token"\s*:\s*"([^"]{20,})"/i,
                                /'token'\s*:\s*'([^']{20,})'/i,
                            ];
                            for (const pattern of patterns) {
                                const match = String(text).match(pattern);
                                if (match && match[1]) return match[1];
                            }
                            return null;
                        };

                        const storageSources = [window.localStorage, window.sessionStorage];
                        for (const storage of storageSources) {
                            try {
                                for (let index = 0; index < storage.length; index += 1) {
                                    const key = storage.key(index);
                                    const value = storage.getItem(key);
                                    const match = scan(key) || scan(value);
                                    if (match) return match;
                                }
                            } catch (error) {
                                // ignore storage access issues and continue
                            }
                        }

                        const htmlMatch = scan(document.documentElement ? document.documentElement.innerHTML : "");
                        if (htmlMatch) return htmlMatch;

                        const response = await fetch("/backend/raw/coveo/CoveoToken", {
                            credentials: "include",
                            headers: {
                                accept: "application/json, text/javascript, */*; q=0.01",
                                "x-requested-with": "XMLHttpRequest",
                                origin: "https://me.sap.com",
                                referer: "https://me.sap.com/search",
                            },
                        });

                        const bodyText = await response.text();
                        const bodyMatch = scan(bodyText);
                        if (bodyMatch) return bodyMatch;

                        try {
                            const payload = JSON.parse(bodyText);
                            return payload.token || payload.accessToken || payload.bearerToken || null;
                        } catch (error) {
                            return null;
                        }
                    }"""
                )

                return str(extracted) if extracted else None
            finally:
                browser.close()

    def _build_coveo_search_body(self, query: str, max_results: int) -> dict:
        return {
            "locale": "en-US",
            "tab": "All",
            "q": query,
            "searchHub": "SAP for Me",
            "sortCriteria": "relevancy",
            "numberOfResults": max_results,
            "firstResult": 0,
            "fieldsToInclude": [
                "language",
                "date",
                "mh_description",
                "mh_id",
                "mh_app_component",
                "mh_alt_url",
                "mh_priority",
            ],
            "facets": [
                {
                    "field": "documenttype",
                    "type": "specific",
                    "currentValues": [{"value": "SAP Note", "state": "selected"}],
                    "numberOfValues": 10,
                }
            ],
            "enableDidYouMean": False,
        }

    def _parse_coveo_response(self, data: dict) -> list[dict]:
        out: list[dict] = []

        for item in data.get("results", []):
            raw = item.get("raw", {})
            note_id = raw.get("mh_id") or "unknown"
            language_raw = raw.get("language")
            if isinstance(language_raw, list):
                language = language_raw[0] if language_raw else "EN"
            else:
                language = language_raw or "EN"

            component_raw = raw.get("mh_app_component")
            if isinstance(component_raw, list):
                component = component_raw[0] if component_raw else None
            else:
                component = component_raw

            release_date = "Unknown"
            date_raw = raw.get("date")
            if date_raw:
                try:
                    release_date = time.strftime("%Y-%m-%d", time.gmtime(int(date_raw) / 1000))
                except Exception:
                    release_date = "Unknown"

            out.append(
                {
                    "id": str(note_id),
                    "title": item.get("title") or "Unknown Title",
                    "summary": item.get("excerpt") or raw.get("mh_description") or "No summary available",
                    "component": component,
                    "releaseDate": release_date,
                    "language": str(language),
                    "url": raw.get("mh_alt_url") or item.get("clickUri") or f"https://launchpad.support.sap.com/#/notes/{note_id}",
                }
            )

        return out

    def _parse_raw_note_response(self, payload: str, note_id: str) -> dict | None:
        try:
            data = json.loads(payload)
        except Exception:
            if "fragmentAfterLogin" in payload and re.fullmatch(r"\d{6,8}", note_id):
                return {
                    "id": note_id,
                    "title": f"SAP Note {note_id}",
                    "summary": "Note found but complete content requires browser access",
                    "content": f"Open https://launchpad.support.sap.com/#/notes/{note_id} for full content.",
                    "language": "EN",
                    "releaseDate": "Unknown",
                    "url": f"https://launchpad.support.sap.com/#/notes/{note_id}",
                }
            return None

        if data.get("Response", {}).get("SAPNote"):
            return self._map_sapnote_detail(data["Response"]["SAPNote"], note_id)

        if data.get("SapNote") or data.get("id"):
            return {
                "id": data.get("SapNote") or data.get("id") or note_id,
                "title": data.get("Title") or data.get("title") or data.get("ShortText") or f"SAP Note {note_id}",
                "summary": data.get("Summary") or data.get("summary") or data.get("Abstract") or "SAP Note details",
                "content": data.get("Content") or data.get("content") or data.get("Text") or data.get("LongText") or "Content not available",
                "language": data.get("Language") or "EN",
                "releaseDate": data.get("ReleaseDate") or "Unknown",
                "component": data.get("Component"),
                "priority": data.get("Priority"),
                "category": data.get("Category"),
                "url": f"https://launchpad.support.sap.com/#/notes/{note_id}",
            }

        return None

    def _map_sapnote_detail(self, sap_note: dict, note_id: str) -> dict:
        header = sap_note.get("Header", {})
        detail = {
            "id": header.get("Number", {}).get("value") or note_id,
            "title": sap_note.get("Title", {}).get("value") or f"SAP Note {note_id}",
            "summary": header.get("Type", {}).get("value") or "SAP Knowledge Base Article",
            "content": sap_note.get("LongText", {}).get("value") or "No content available",
            "language": header.get("Language", {}).get("value") or "EN",
            "releaseDate": header.get("ReleasedOn", {}).get("value") or "Unknown",
            "component": header.get("SAPComponentKey", {}).get("value"),
            "componentText": header.get("SAPComponentKeyText", {}).get("value"),
            "priority": header.get("Priority", {}).get("value"),
            "category": header.get("Category", {}).get("value"),
            "version": str(header.get("Version", {}).get("value")) if header.get("Version", {}).get("value") is not None else None,
            "status": header.get("Status", {}).get("value"),
            "url": f"https://launchpad.support.sap.com/#/notes/{note_id}",
        }

        self._extract_enriched_metadata(sap_note, detail)
        return detail

    def _extract_enriched_metadata(self, sap_note: dict, detail: dict) -> None:
        validity_items = ((sap_note.get("Validity") or {}).get("Items") or [])
        if validity_items:
            detail["validity"] = [
                {
                    "softwareComponent": item.get("Name", {}).get("value") or item.get("SoftwareComponentID", {}).get("value") or "",
                    "versionFrom": item.get("VersionFrom", {}).get("value") or "",
                    "versionTo": item.get("VersionTo", {}).get("value") or "",
                }
                for item in validity_items
                if item.get("Name", {}).get("value") or item.get("SoftwareComponentID", {}).get("value")
            ]

        corr_items = ((sap_note.get("CorrectionInstructions") or {}).get("Items") or [])
        if corr_items:
            detail["correctionsSummary"] = [
                {
                    "softwareComponent": item.get("Name", {}).get("value") or item.get("SoftwareComponentName", {}).get("value") or "",
                    "pakId": self._extract_pak_id(item.get("URL", {}).get("value") or "") or item.get("PakId", {}).get("value") or "",
                    "count": int(item.get("Count", {}).get("value")) if item.get("Count", {}).get("value") else None,
                }
                for item in corr_items
                if item.get("Name", {}).get("value") or item.get("SoftwareComponentName", {}).get("value")
            ]

        pre_items = ((sap_note.get("Preconditions") or {}).get("Items") or [])
        if pre_items:
            detail["prerequisites"] = [
                {
                    "noteNumber": item.get("SAPNoteNumber", {}).get("value") or item.get("Number", {}).get("value") or "",
                    "title": item.get("Title", {}).get("value") or "",
                }
                for item in pre_items
                if item.get("SAPNoteNumber", {}).get("value") or item.get("Number", {}).get("value")
            ]

        corr_info = sap_note.get("CorrectionsInfo") or {}
        if corr_info:
            detail["correctionsInfo"] = {
                "totalCorrections": int(corr_info.get("TotalCorrections", {}).get("value")) if corr_info.get("TotalCorrections", {}).get("value") else None,
                "totalManualActivities": int(corr_info.get("TotalManualActivities", {}).get("value")) if corr_info.get("TotalManualActivities", {}).get("value") else None,
                "totalPrerequisites": int(corr_info.get("TotalPrerequisites", {}).get("value")) if corr_info.get("TotalPrerequisites", {}).get("value") else None,
            }

        attachments = ((sap_note.get("Attachments") or {}).get("Items") or [])
        if attachments:
            detail["attachments"] = [
                {
                    "filename": item.get("Filename", {}).get("value") or item.get("Name", {}).get("value") or "unknown",
                    "url": item.get("URL", {}).get("value"),
                }
                for item in attachments
            ]

        manual_actions = (sap_note.get("ManualActions") or {}).get("value")
        if manual_actions:
            detail["manualActions"] = manual_actions

        download_url = ((sap_note.get("Actions") or {}).get("Download") or {}).get("url")
        if download_url:
            detail["downloadUrl"] = download_url

    def _extract_pak_id(self, raw_url: str) -> str | None:
        match = re.search(r"corrins/\d+/(\d+)", raw_url)
        return match.group(1) if match else None

    def _fetch_corrins_set(self, padded_note_id: str, pak_id: str, token: str) -> list[dict]:
        url = (
            "https://me.sap.com/backend/raw/core/W7LegacyProxyVerticle/odata/svt/snogwscorrins/"
            f"CorrInsSet?$filter=SapNotesNumber eq '{padded_note_id}' and PakId eq '{pak_id}'&$format=json"
        )
        response = requests.get(
            url,
            headers={
                "accept": "application/json",
                "cookie": self._format_cookie_header(token),
                "origin": "https://me.sap.com",
                "referer": "https://me.sap.com/",
            },
            timeout=30,
        )
        if not response.ok:
            return []
        return ((response.json().get("d") or {}).get("results") or [])

    def _fetch_corrins_navigation(self, entry: dict, nav_property: str, token: str) -> list[dict]:
        key_parts = ",".join(
            [
                f"Aleid='{entry.get('Aleid', '')}'",
                f"PakId='{entry.get('PakId', '')}'",
                f"Insta='{entry.get('Insta', '')}'",
                f"Vernr='{entry.get('Vernr', '')}'",
                f"Name='{entry.get('Name', '')}'",
                f"VerFrom='{entry.get('VerFrom', '')}'",
                f"VerTo='{entry.get('VerTo', '')}'",
            ]
        )
        url = (
            "https://me.sap.com/backend/raw/core/W7LegacyProxyVerticle/odata/svt/snogwscorrins/"
            f"CorrInsSet({key_parts})/{nav_property}?$format=json"
        )
        response = requests.get(
            url,
            headers={
                "accept": "application/json",
                "cookie": self._format_cookie_header(token),
                "origin": "https://me.sap.com",
                "referer": "https://me.sap.com/",
            },
            timeout=30,
        )
        if not response.ok:
            return []
        payload = response.json().get("d") or {}
        if isinstance(payload.get("results"), list):
            return payload["results"]
        return [payload] if payload else []

    def _format_cookie_header(self, sap_token: str) -> str:
        if "=" in sap_token:
            return sap_token

        cache_file = Path("token-cache.json")
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
                cookies = cache.get("cookies") or []
                if cookies:
                    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value"))
            except Exception as error:  # noqa: BLE001
                logger.warning("Could not load cookies from cache: %s", error)

        return sap_token

    def _get_note_with_playwright(self, note_id: str, token: str) -> dict | None:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not self._config.headful,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
            )
            try:
                context = browser.new_context(ignore_https_errors=True)
                cookies = self._parse_cookies_from_token(self._format_cookie_header(token))
                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception as error:  # noqa: BLE001
                        logger.warning("Could not inject cookies into Playwright context: %s", error)

                page = context.new_page()
                response = page.goto(
                    f"https://me.sap.com/backend/raw/sapnotes/Detail?q={note_id}&t=E&isVTEnabled=false",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                if not response or not response.ok:
                    return None

                page.wait_for_timeout(1500)
                body_text = page.locator("body").text_content() or ""
                return self._parse_raw_note_response(body_text.strip(), note_id)
            finally:
                browser.close()

    def _parse_cookies_from_token(self, token: str) -> list[dict]:
        cookies: list[dict] = []
        for pair in token.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"')
            if not name or not value:
                continue
            if name.lower() in {"path", "domain", "secure", "httponly", "samesite", "max-age", "expires"}:
                continue
            # Use a concrete URL instead of broad domain cookies to avoid
            # Protocol-level validation issues (for example __Host-* cookies).
            cookies.append({"name": name, "value": value, "url": "https://me.sap.com"})
        return cookies
