from __future__ import annotations

import re
from html import unescape


def strip_html(html: str) -> str:
    text = html
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|li|div|h[1-6]|tr|ol|ul)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", r"[\1]", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_note_sections(html: str) -> list[dict[str, str]]:
    pattern = re.compile(r"<h3[^>]*class=\"section\"[^>]*id=\"([^\"]*)\"[^>]*>([^<]*)</h3>", re.IGNORECASE)
    matches = list(pattern.finditer(html))

    if not matches:
        plain = strip_html(html)
        return [{"heading": "Content", "content": plain}] if plain else []

    sections: list[dict[str, str]] = []
    for idx, match in enumerate(matches):
        heading = (match.group(2) or match.group(1) or "Content").strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
        section_html = html[start:end]
        content = strip_html(section_html)
        if content:
            sections.append({"heading": heading, "content": content})

    return sections


def parse_note_content(html: str) -> dict[str, object]:
    sections = parse_note_sections(html)
    plain_text = "\n\n".join(f"## {s['heading']}\n{s['content']}" for s in sections)
    return {"sections": sections, "plainText": plain_text}
