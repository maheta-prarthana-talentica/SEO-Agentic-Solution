"""Crawl & Audit Agent (Section 5.1).

Crawls the live site (or the offline fixture), extracts per-page DOM signals, and
(optionally) enriches with Core Web Vitals via PageSpeed Insights (FR-1.1, FR-1.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tools.crawler import PageRecord, crawl_site, render_with_playwright
from tools.logging_utils import TraceLogger
from tools.psi_client import CoreWebVitals, get_core_web_vitals
from tools.robots_sitemap import RobotsAnalysis, SitemapAnalysis, analyze_robots_txt, analyze_sitemap_xml

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_site"


@dataclass
class CrawlResult:
    pages: list[PageRecord]
    robots: RobotsAnalysis
    sitemap: SitemapAnalysis
    core_web_vitals: CoreWebVitals | None
    base_url: str


def run(target_url: str, page_limit: int = 50, use_fixture: bool = False,
        trace: TraceLogger | None = None) -> CrawlResult:
    """Entry point used by the orchestrator."""
    if use_fixture:
        return _crawl_fixture(trace)

    robots = analyze_robots_txt(target_url)
    if trace:
        trace.log("CrawlAuditAgent", "robots_analyzed",
                  {"exists": robots.exists, "issues": len(robots.issues)})

    sitemap_url = robots.sitemap_urls[0] if robots.sitemap_urls else None
    sitemap = analyze_sitemap_xml(target_url, sitemap_url)
    if trace:
        trace.log("CrawlAuditAgent", "sitemap_analyzed",
                  {"exists": sitemap.exists, "url_count": sitemap.url_count})

    pages = crawl_site(target_url, page_limit=page_limit, robots=robots)
    if trace:
        trace.log("CrawlAuditAgent", "crawl_complete",
                  {"pages": len(pages), "page_limit": page_limit})

    # Optional Playwright enrichment on the entry URL only (mobile-viewport signal).
    if pages and render_with_playwright(pages[0].url) is None and trace:
        trace.log("CrawlAuditAgent", "playwright_skipped",
                  {"reason": "not installed or render failed"})

    cwv = get_core_web_vitals(target_url)
    if trace:
        trace.log("CrawlAuditAgent", "cwv_fetched",
                  {"is_assumed": cwv.is_assumed, "source": cwv.source_note[:80]})

    return CrawlResult(pages=pages, robots=robots, sitemap=sitemap,
                       core_web_vitals=cwv, base_url=target_url)


def _crawl_fixture(trace: TraceLogger | None = None) -> CrawlResult:
    """Offline crawl of tests/fixtures/sample_site so the report format can be demosned
    without network access (per Phase 1 plan: 'demoed against a placeholder site')."""
    if not FIXTURE_DIR.exists():
        raise FileNotFoundError(f"Fixture site not found at {FIXTURE_DIR}")

    base_url = "https://fixture.example.com"
    html_files = sorted(FIXTURE_DIR.glob("*.html"))
    pages: list[PageRecord] = []

    for path in html_files:
        html = path.read_text(encoding="utf-8")
        pages.append(_parse_fixture_html(urljoin(base_url + "/", path.name), html))

    robots_path = FIXTURE_DIR / "robots.txt"
    if robots_path.exists():
        content = robots_path.read_text(encoding="utf-8")
        robots = RobotsAnalysis(
            exists=True, fetch_status=200, content=content,
            disallow_all="disallow: /" in content.lower() and "allow:" not in content.lower(),
            sitemap_urls=[], issues=["robots.txt does not declare a Sitemap: directive"]
            if "sitemap:" not in content.lower() else [],
        )
    else:
        robots = RobotsAnalysis(exists=False, fetch_status=404,
                                issues=["robots.txt is missing"])

    sitemap_path = FIXTURE_DIR / "sitemap.xml"
    if sitemap_path.exists():
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(sitemap_path.read_text(encoding="utf-8"))
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            urls = [loc.text.strip() for loc in root.iter(f"{ns}loc") if loc.text]
            sitemap = SitemapAnalysis(exists=True, fetch_status=200, url_count=len(urls),
                                      urls=urls, issues=[])
        except ET.ParseError as exc:
            sitemap = SitemapAnalysis(exists=True, fetch_status=200, is_valid_xml=False,
                                      issues=[f"malformed XML: {exc}"])
    else:
        sitemap = SitemapAnalysis(exists=False, fetch_status=404,
                                  issues=["sitemap.xml is missing"])

    cwv = CoreWebVitals(
        lcp_seconds=None, cls=None, inp_ms=None, performance_score=None, is_assumed=True,
        source_note="Fixture mode — Core Web Vitals not measured. Common LCP/CLS issues assumed.",
    )

    if trace:
        trace.log("CrawlAuditAgent", "fixture_crawl_complete", {"pages": len(pages)})

    return CrawlResult(pages=pages, robots=robots, sitemap=sitemap,
                       core_web_vitals=cwv, base_url=base_url)


def _parse_fixture_html(url: str, html: str) -> PageRecord:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    canonical = soup.find("link", attrs={"rel": "canonical"})
    meta_robots = soup.find("meta", attrs={"name": "robots"})
    headings = [(h.name, h.get_text(strip=True))
                for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]
    images = [(img.get("src", ""), img.get("alt")) for img in soup.find_all("img")]
    internal_links, external_links = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            external_links.append(href)
        else:
            internal_links.append(urljoin(url, href))
    json_ld = [t.string for t in soup.find_all("script", attrs={"type": "application/ld+json"})
               if t.string]
    body_text = soup.get_text(separator=" ", strip=True)
    return PageRecord(
        url=url, status_code=200, redirect_chain=[],
        title=title_tag.get_text(strip=True) if title_tag else None,
        meta_description=meta_desc.get("content", "").strip() if meta_desc else None,
        canonical=canonical.get("href") if canonical else None,
        meta_robots=meta_robots.get("content") if meta_robots else None,
        headings=headings, images=images, internal_links=internal_links,
        external_links=external_links, json_ld_blocks=json_ld,
        word_count=len(body_text.split()), raw_html_bytes=len(html.encode("utf-8")),
    )
