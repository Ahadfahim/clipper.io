"""Linked rule documents. Whop campaigns keep their real requirements in a Google Doc linked from the
campaign page, and the brief reader needs its text. A public Google Doc exports as plain text without
logging in; a private one redirects to a login page and gives nothing (the brief says to open it).

The text is third-party and untrusted, exactly like the campaign page (PLAN §4).
"""

from __future__ import annotations

import re

import httpx

GOOGLE_DOC = re.compile(r"^https://docs\.google\.com/document/d/([\w-]{20,})")
MAX_CHARS = 30_000


async def fetch_doc_text(url: str, *, timeout_s: float = 20.0) -> str | None:
    """Plain text of a public Google Doc, or None (not a Google Doc, private, or unreachable)."""
    m = GOOGLE_DOC.match(url)
    if m is None:
        return None
    export = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            res = await client.get(export)
    except httpx.HTTPError:
        return None
    if res.status_code != 200 or not res.headers.get("content-type", "").startswith("text/plain"):
        return None
    return res.text.lstrip("\ufeff")[:MAX_CHARS].strip() or None
