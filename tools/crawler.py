"""Site crawler used by agents/crawl_audit_agent.py.

FR-1.1: crawl a domain up to a configurable page limit, respecting robots.txt.

Primary path uses httpx + BeautifulSoup (no extra system deps). If Playwright is
installed, `render_with_playwright=True` can be passed to additionally capture the
rendered DOM for JS-heavy pages -- this is best-effort and never blocks the crawl.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from tools.http_client import fetch
from tools.robots_sitemap import RobotsAnalysis

try:
    from playwright.sync_api import sync_playwright  # type: ignore

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False


@dataclass
class PageRecord:
    url: str
    status_code: int
    redirect_chain: list[str]
    title: str | None
    meta_description: str | None
    canonical: str | None
    meta_robots: str | None
    headings: list[tuple[str, str]] = field(default_factory=list)  # [("h1", "text"), ...]
    images: list[tuple[str, str | None]] = field(default_factory=list)  # [(src, alt), ...]
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    json_ld_blocks: list[str] = field(default_factory=list)
    word_count: int = 0
    raw_html_bytes: int = 0
    error: str | None = None


def _same_domain(url: str, domain: str) -> bool:
    return urlparse(url).netloc.replace("www.", "") == domain.replace("www.", "")


def crawl_site(base_url: str, page_limit: int = 50,
                robots: RobotsAnalysis | None = None) -> list[PageRecord]:
    """Breadth-first crawl starting at base_url, same-domain only, honoring robots.txt disallow rules."""
    domain = urlparse(base_url).netloc
    seen: set[str] = set()
    queue: list[str] = [base_url]
    records: list[PageRecord] = []

    while queue and len(records) < page_limit:
        url = queue.pop(0)
        norm = url.split("#")[0].rstrip("/")
        if norm in seen:
            continue
        seen.add(norm)

        if robots and robots.parser and not robots.parser.can_fetch("*", url):
            continue

        record, links = _fetch_and_parse(url, domain)
        records.append(record)
        for link in links:
            if link.split("#")[0].rstrip("/") not in seen:
                queue.append(link)

    return records


def _fetch_and_parse(url: str, domain: str) -> tuple[PageRecord, list[str]]:
    result = fetch(url)
    if result.status_code == 0:
        return PageRecord(url=url, status_code=0, redirect_chain=result.redirect_chain, title=None,
                           meta_description=None, canonical=None, meta_robots=None,
                           error=result.error), []

    if result.status_code >= 400 or not result.text:
        return PageRecord(url=url, status_code=result.status_code, redirect_chain=result.redirect_chain,
                           title=None, meta_description=None, canonical=None, meta_robots=None), []

    soup = BeautifulSoup(result.text, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = meta_desc_tag.get("content", "").strip() if meta_desc_tag else None

    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical = canonical_tag.get("href") if canonical_tag else None

    meta_robots_tag = soup.find("meta", attrs={"name": "robots"})
    meta_robots = meta_robots_tag.get("content") if meta_robots_tag else None

    headings = [(h.name, h.get_text(strip=True)) for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]

    images = [(img.get("src", ""), img.get("alt")) for img in soup.find_all("img")]

    internal_links, external_links, discovered = [], [], []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if not href.startswith(("http://", "https://")):
            continue
        if _same_domain(href, domain):
            internal_links.append(href)
            discovered.append(href)
        else:
            external_links.append(href)

    json_ld_blocks = [tag.string for tag in soup.find_all("script", attrs={"type": "application/ld+json"})
                      if tag.string]

    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())

    record = PageRecord(
        url=result.url, status_code=result.status_code, redirect_chain=result.redirect_chain,
        title=title, meta_description=meta_description, canonical=canonical, meta_robots=meta_robots,
        headings=headings, images=images, internal_links=internal_links, external_links=external_links,
        json_ld_blocks=json_ld_blocks, word_count=word_count, raw_html_bytes=len(result.text.encode("utf-8")),
    )
    return record, discovered


def render_with_playwright(url: str) -> dict | None:
    """Best-effort JS-rendered snapshot for mobile-viewport / CLS-adjacent checks.

    Returns None if Playwright (or its browser binaries) is not available -- callers must
    treat this as optional enrichment, never a hard dependency.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 375, "height": 667})  # mobile viewport
            page.goto(url, wait_until="networkidle", timeout=15000)
            viewport_meta = page.locator("meta[name=viewport]").count()
            html = page.content()
            browser.close()
            return {"has_viewport_meta": viewport_meta > 0, "rendered_html_len": len(html)}
    except Exception:  # noqa: BLE001 - rendering is best-effort enrichment only
        return None
