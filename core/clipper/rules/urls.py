"""URL helpers for the source whitelist and the browser domain allowlist. Pure functions."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

_YT_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "youtube-nocookie.com"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TRACKING_PARAMS = {"si", "feature", "pp", "ab_channel", "t", "start", "fbclid", "gclid", "igshid"}


def host_of(url: str) -> str:
    """Lower-cased host without ``www.`` (empty string if the URL has no host)."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def domain_allowed(url: str, allowed_domains: list[str] | set[str] | tuple[str, ...]) -> bool:
    """True if the URL's host is one of ``allowed_domains`` or a subdomain of one. https/http only."""
    try:
        scheme = urlsplit(url.strip()).scheme.lower()
    except ValueError:
        return False
    if scheme not in {"https", "http"}:
        return False
    host = host_of(url)
    if not host:
        return False
    for domain in allowed_domains:
        d = domain.lower().lstrip(".")
        if d.startswith("www."):
            d = d[4:]
        if host == d or host.endswith("." + d):
            return True
    return False


def youtube_id(url: str) -> str | None:
    parts = urlsplit(url.strip())
    host = host_of(url)
    if host not in _YT_HOSTS:
        return None
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
        return candidate if _YT_ID.match(candidate) else None
    query = dict(parse_qsl(parts.query))
    if parts.path == "/watch" and _YT_ID.match(query.get("v", "")):
        return query["v"]
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) >= 2 and segs[0] in {"shorts", "live", "embed", "v"} and _YT_ID.match(segs[1]):
        return segs[1]
    return None


def canonical_source(url: str) -> str:
    """A stable key for comparing source URLs (YouTube/TikTok ids, otherwise host+path+query)."""
    yid = youtube_id(url)
    if yid:
        return f"youtube:{yid}"
    parts = urlsplit(url.strip())
    host = host_of(url)
    m = re.search(r"/video/(\d+)", parts.path)
    if host.endswith("tiktok.com") and m:
        return f"tiktok:{m.group(1)}"
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query) if k not in _TRACKING_PARAMS and not k.startswith("utm_")
    )
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}" + (f"?{urlencode(query)}" if query else "")


def source_whitelisted(url: str, whitelist: list[str]) -> bool:
    if not url.strip().lower().startswith(("https://", "http://")):
        return False
    key = canonical_source(url)
    return any(canonical_source(entry) == key for entry in whitelist if entry.strip())
