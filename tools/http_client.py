"""Small httpx wrapper shared by the crawler, robots/sitemap parser, and PSI client.

Kept dependency-light on purpose: `httpx` is the only hard network dependency for the
Phase 1 audit path (Playwright is optional/best-effort for JS-rendered checks).
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

DEFAULT_TIMEOUT = 10.0
USER_AGENT = "SEOAgenticSolutions-AuditBot/0.1 (+https://github.com/; POC crawler, respects robots.txt)"


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    headers: dict[str, str]
    redirect_chain: list[str]
    error: str | None = None


def fetch(url: str, timeout: float = DEFAULT_TIMEOUT, follow_redirects: bool = True) -> FetchResult:
    """Fetches a URL, capturing the redirect chain (FR-1.2) and never raising on HTTP errors."""
    redirect_chain: list[str] = []
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            for hist in response.history:
                redirect_chain.append(str(hist.url))
            return FetchResult(
                url=str(response.url),
                status_code=response.status_code,
                text=response.text if _looks_textual(response) else "",
                headers=dict(response.headers),
                redirect_chain=redirect_chain,
            )
    except httpx.HTTPError as exc:
        return FetchResult(url=url, status_code=0, text="", headers={}, redirect_chain=redirect_chain,
                            error=str(exc))


def _looks_textual(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return any(t in content_type for t in ("text/", "application/xml", "application/json", "application/xhtml"))
