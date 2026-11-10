"""Safe parsing of Bilibili share links.

The mobile app commonly copies a title followed by a ``b23.tv`` URL.  Keep
that parsing and the network redirect handling outside the API layer so it can
be tested without a database or a pipeline worker.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Optional


class BilibiliShareError(ValueError):
    """A Bilibili share link was recognised but cannot safely identify a video."""


_URL_RE = re.compile(r"https?://[^\s<>\[\]{}\"']+", re.IGNORECASE)
_SHORT_HOSTS = frozenset({"b23.tv", "www.b23.tv", "bili2233.cn", "www.bili2233.cn"})
_MAX_REDIRECTS = 5
_TOTAL_TIMEOUT_SECONDS = 8.0


def _hostname(url: str) -> Optional[str]:
    try:
        hostname = urllib.parse.urlsplit(url).hostname
        return hostname.lower() if hostname else None
    except ValueError:
        return None


def _is_bilibili_host(host: Optional[str]) -> bool:
    return bool(host) and (host == "bilibili.com" or host.endswith(".bilibili.com"))


def _is_allowed_redirect_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port  # Accessing it also rejects malformed port text.
    except ValueError:
        return False
    host = _hostname(url)
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and port in (None, 443)
        and (host in _SHORT_HOSTS or _is_bilibili_host(host))
    )


def _is_bilibili_video_url(url: str) -> bool:
    """Whether a redirect already reached a canonical Bilibili video URL."""
    try:
        path = urllib.parse.urlsplit(url).path
    except ValueError:
        return False
    return bool(re.search(r"^/video/(?:BV[0-9A-Za-z]{10}|av\d+)(?:/|$)", path, re.IGNORECASE))


def extract_bilibili_url(share_text: str) -> Optional[str]:
    """Return the first Bilibili URL embedded in a pasted share message."""
    for match in _URL_RE.finditer(share_text or ""):
        # Chinese prose often follows a copied URL without whitespace.
        candidate = match.group(0).rstrip(".,!?;:，。！？；：")
        host = _hostname(candidate)
        if host in _SHORT_HOSTS or _is_bilibili_host(host):
            return candidate
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface every redirect to the caller for per-hop validation."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _open_without_redirects(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def resolve_bilibili_short_link(
    url: str,
    *,
    open_request: Callable[[urllib.request.Request, float], object] = _open_without_redirects,
) -> str:
    """Resolve a Bilibili short URL while allowing only HTTPS Bilibili hops."""
    current = (url or "").strip()
    if _hostname(current) not in _SHORT_HOSTS:
        raise BilibiliShareError("不是可解析的 Bilibili 短連結")
    if not _is_allowed_redirect_url(current):
        raise BilibiliShareError("Bilibili 短連結必須使用 HTTPS")

    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    for _ in range(_MAX_REDIRECTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BilibiliShareError("解析 Bilibili 短連結逾時")
        request = urllib.request.Request(current, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        try:
            response = open_request(request, remaining)
        except urllib.error.HTTPError as exc:
            try:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise BilibiliShareError(f"Bilibili 短連結回應 HTTP {exc.code}") from exc
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    raise BilibiliShareError("Bilibili 短連結重新導向缺少位置") from exc
                next_url = urllib.parse.urljoin(current, location)
                if not _is_allowed_redirect_url(next_url):
                    raise BilibiliShareError("Bilibili 短連結重新導向到不允許的網域") from exc
                # A final BVID/av URL needs no page fetch.  This avoids a
                # needless Bilibili anti-bot response after the ID is known.
                if _is_bilibili_host(_hostname(next_url)) and _is_bilibili_video_url(next_url):
                    return next_url
                current = next_url
                continue
            finally:
                exc.close()
        except (OSError, ValueError) as exc:
            raise BilibiliShareError("無法解析 Bilibili 短連結") from exc

        final_url = getattr(response, "geturl", lambda: current)()
        close = getattr(response, "close", None)
        try:
            if not _is_allowed_redirect_url(final_url):
                raise BilibiliShareError("Bilibili 短連結回應了不允許的網域")
            if not _is_bilibili_host(_hostname(final_url)):
                raise BilibiliShareError("Bilibili 短連結未重新導向到影片頁面")
            return final_url
        finally:
            if close:
                close()
    raise BilibiliShareError("Bilibili 短連結重新導向次數過多")


def _reject_multi_part(url: str) -> None:
    try:
        page_values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("p", [])
    except ValueError as exc:
        raise BilibiliShareError("Bilibili 連結格式無效") from exc
    if any(value.isdigit() and int(value) > 1 for value in page_values):
        raise BilibiliShareError("目前不支援 Bilibili 多 P 影片的第 2 頁之後")


def extract_bilibili_video_id(share_text: str) -> Optional[str]:
    """Extract a Bilibili ID from a full pasted share message.

    Returns ``None`` when no Bilibili URL was supplied.  A recognised but
    unusable link raises :class:`BilibiliShareError` so the API can return a
    useful 400 rather than silently queueing the wrong part.
    """
    url = extract_bilibili_url(share_text)
    if not url:
        return None
    final_url = resolve_bilibili_short_link(url) if _hostname(url) in _SHORT_HOSTS else url
    _reject_multi_part(final_url)

    # Imported lazily to keep this module independent of the rest of the
    # pipeline during redirect tests.
    from ktv_pipeline.video_source import extract_video_id

    video_id = extract_video_id(final_url)
    if not video_id or not _is_bilibili_host(_hostname(final_url)):
        raise BilibiliShareError("Bilibili 分享連結未包含可用影片 ID")
    return video_id
