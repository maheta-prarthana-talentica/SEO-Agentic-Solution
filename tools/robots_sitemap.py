"""robots.txt and sitemap.xml parsing, validation, and correction generation.

Implements FR-1.1 (crawl respecting robots.txt) and FR-1.5 (detect missing/invalid
sitemap.xml and robots.txt, propose corrected versions).
"""
from __future__ import annotations

import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from tools.http_client import fetch

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass
class RobotsAnalysis:
    exists: bool
    fetch_status: int
    content: str = ""
    disallow_all: bool = False
    sitemap_urls: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    parser: robotparser.RobotFileParser | None = None


@dataclass
class SitemapAnalysis:
    exists: bool
    fetch_status: int
    url_count: int = 0
    urls: list[str] = field(default_factory=list)
    is_valid_xml: bool = True
    issues: list[str] = field(default_factory=list)


def analyze_robots_txt(base_url: str) -> RobotsAnalysis:
    robots_url = urljoin(base_url, "/robots.txt")
    result = fetch(robots_url)
    if result.status_code != 200 or not result.text:
        return RobotsAnalysis(
            exists=False, fetch_status=result.status_code,
            issues=["robots.txt is missing or unreachable -- crawlers default to full-site allow, "
                    "but this also means you have no way to steer crawl budget or block low-value paths."],
        )

    parser = robotparser.RobotFileParser()
    parser.parse(result.text.splitlines())

    sitemap_urls = [line.split(":", 1)[1].strip() for line in result.text.splitlines()
                    if line.lower().startswith("sitemap:")]

    disallow_all = "disallow: /" in result.text.lower() and "allow:" not in result.text.lower()

    issues = []
    if disallow_all:
        issues.append("robots.txt contains a site-wide 'Disallow: /' with no Allow exceptions -- "
                       "this blocks all search engine crawling.")
    if not sitemap_urls:
        issues.append("robots.txt does not declare a Sitemap: directive, making sitemap discovery "
                       "dependent on manual submission to Search Console.")

    return RobotsAnalysis(
        exists=True, fetch_status=result.status_code, content=result.text,
        disallow_all=disallow_all, sitemap_urls=sitemap_urls, issues=issues, parser=parser,
    )


def analyze_sitemap_xml(base_url: str, sitemap_url: str | None = None) -> SitemapAnalysis:
    target = sitemap_url or urljoin(base_url, "/sitemap.xml")
    result = fetch(target)
    if result.status_code != 200 or not result.text:
        return SitemapAnalysis(
            exists=False, fetch_status=result.status_code,
            issues=["sitemap.xml is missing or unreachable at the default location -- search engines "
                    "must rely purely on discovered-link crawling, slowing indexation of new pages."],
        )

    try:
        root = ET.fromstring(result.text)
    except ET.ParseError as exc:
        return SitemapAnalysis(exists=True, fetch_status=result.status_code, is_valid_xml=False,
                                issues=[f"sitemap.xml is not well-formed XML: {exc}"])

    urls = [loc.text.strip() for loc in root.iter(f"{SITEMAP_NS}loc") if loc.text]
    issues = []
    if not urls:
        issues.append("sitemap.xml parsed but contains no <url><loc> entries.")

    parsed_base = urlparse(base_url).netloc
    off_domain = [u for u in urls if urlparse(u).netloc and urlparse(u).netloc != parsed_base]
    if off_domain:
        issues.append(f"{len(off_domain)} sitemap URL(s) point to a different domain than the audited "
                       f"site ({parsed_base}); likely a stale or misconfigured sitemap.")

    return SitemapAnalysis(exists=True, fetch_status=result.status_code, url_count=len(urls), urls=urls,
                            issues=issues)


def generate_corrected_robots_txt(base_url: str, disallow_paths: list[str] | None = None) -> str:
    """FR-1.5 auto-fix: a minimal, safe default robots.txt."""
    disallow_paths = disallow_paths or ["/admin/", "/api/", "/*?*sort=", "/*?*filter="]
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    lines = ["User-agent: *"]
    lines += [f"Disallow: {p}" for p in disallow_paths]
    lines.append("Allow: /")
    lines.append("")
    lines.append(f"Sitemap: {sitemap_url}")
    return "\n".join(lines) + "\n"


def generate_corrected_sitemap_xml(urls: list[str]) -> str:
    """FR-1.5 auto-fix: regenerate a well-formed sitemap.xml from a known-good URL list."""
    entries = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )
