"""Technical SEO Agent (Section 5.1).

Evaluates robots.txt, sitemap.xml, canonicalization, redirects, status codes, and
crawlability -- FR-1.1, FR-1.2, FR-1.5.
"""
from __future__ import annotations

from urllib.parse import urlparse

from backend.models import Category, Finding, FixType, Severity
from tools.crawler import PageRecord
from tools.robots_sitemap import RobotsAnalysis, SitemapAnalysis


def run(base_url: str, pages: list[PageRecord], robots: RobotsAnalysis,
        sitemap: SitemapAnalysis) -> list[Finding]:
    findings: list[Finding] = []

    findings.extend(_robots_findings(robots))
    findings.extend(_sitemap_findings(sitemap, pages))
    findings.extend(_status_code_findings(pages))
    findings.extend(_redirect_chain_findings(pages))
    findings.extend(_canonical_findings(base_url, pages))
    findings.extend(_indexability_findings(pages))

    return findings


def _robots_findings(robots: RobotsAnalysis) -> list[Finding]:
    findings = []
    if not robots.exists:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.HIGH,
            title="robots.txt is missing",
            description="No robots.txt was found at the site root.",
            evidence="GET /robots.txt did not return 200 with content.",
            recommendation="Add a robots.txt at the domain root declaring crawl rules and a Sitemap: "
                           "directive. Without it, crawlers fall back to default full-access behavior, "
                           "which is usually fine, but you lose the ability to steer crawl budget away "
                           "from low-value paths (search, filters, admin).",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=["Site-wide"], impact_score=3, effort_score=1,
        ))
        return findings

    if robots.disallow_all:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.CRITICAL,
            title="robots.txt blocks all crawling",
            description="robots.txt contains a site-wide 'Disallow: /' with no scoped Allow exceptions.",
            evidence="robots.txt content includes 'Disallow: /'.",
            recommendation="Remove or scope the site-wide Disallow rule immediately -- this is actively "
                           "preventing indexation of the entire site.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=["Site-wide"], impact_score=5, effort_score=1,
        ))

    for issue in robots.issues:
        if "Sitemap:" in issue or "sitemap" in issue.lower():
            findings.append(Finding(
                category=Category.TECHNICAL, severity=Severity.LOW,
                title="robots.txt does not declare a Sitemap directive",
                description=issue,
                evidence="No 'Sitemap:' line found in robots.txt.",
                recommendation="Add 'Sitemap: <absolute-sitemap-url>' to robots.txt so crawlers can "
                               "auto-discover it without relying on manual Search Console submission.",
                fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
                affected_pages=["Site-wide"], impact_score=2, effort_score=1,
            ))
    return findings


def _sitemap_findings(sitemap: SitemapAnalysis, pages: list[PageRecord]) -> list[Finding]:
    findings = []
    if not sitemap.exists:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.MEDIUM,
            title="sitemap.xml is missing",
            description="No sitemap.xml was found at the default location.",
            evidence="GET /sitemap.xml did not return 200 with parseable content.",
            recommendation="Generate and publish a sitemap.xml listing all indexable URLs, and "
                           "reference it from robots.txt.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=["Site-wide"], impact_score=3, effort_score=1,
        ))
        return findings

    if not sitemap.is_valid_xml:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.HIGH,
            title="sitemap.xml is malformed",
            description="sitemap.xml exists but is not well-formed XML.",
            evidence="; ".join(sitemap.issues) or "XML parse error.",
            recommendation="Regenerate sitemap.xml from the site's known URL list using a standards-"
                           "compliant sitemap generator to guarantee well-formed output.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=["Site-wide"], impact_score=4, effort_score=1,
        ))
        return findings

    for issue in sitemap.issues:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.MEDIUM,
            title="sitemap.xml content issue",
            description=issue,
            evidence=issue,
            recommendation="Regenerate sitemap.xml to only include canonical, same-domain, indexable URLs.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=["Site-wide"], impact_score=2, effort_score=1,
        ))

    crawled_urls = {p.url for p in pages}
    missing_from_sitemap = crawled_urls - set(sitemap.urls)
    if missing_from_sitemap and sitemap.url_count > 0:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.LOW,
            title="Crawled pages are missing from sitemap.xml",
            description=f"{len(missing_from_sitemap)} of {len(crawled_urls)} crawled pages are not "
                        "listed in sitemap.xml.",
            evidence=f"Example missing URL(s): {list(missing_from_sitemap)[:3]}",
            recommendation="Ensure sitemap generation covers every publicly linked, indexable page; "
                           "regenerate from the current route list rather than a stale cache.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="sitemap_or_robots_error",
            affected_pages=list(missing_from_sitemap)[:10], impact_score=2, effort_score=2,
        ))
    return findings


def _status_code_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    broken = [p for p in pages if p.status_code >= 400 or p.status_code == 0]
    if broken:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.HIGH,
            title="Broken pages / links (4xx, 5xx, or unreachable)",
            description=f"{len(broken)} crawled URL(s) returned a client/server error or were unreachable.",
            evidence="; ".join(f"{p.url} -> {p.status_code or 'unreachable: ' + (p.error or '')}"
                                for p in broken[:5]),
            recommendation="Fix or remove the broken destination, or 301-redirect it to the correct "
                           "current URL. Update any internal links pointing at these URLs.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="broken_internal_link",
            affected_pages=[p.url for p in broken], impact_score=4, effort_score=2,
        ))
    return findings


def _redirect_chain_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    multi_hop = [p for p in pages if len(p.redirect_chain) >= 2]
    if multi_hop:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.MEDIUM,
            title="Multi-hop redirect chains",
            description=f"{len(multi_hop)} URL(s) resolve through 2+ redirect hops before reaching "
                        "their final destination.",
            evidence="; ".join(f"{p.url}: {' -> '.join(p.redirect_chain)}" for p in multi_hop[:3]),
            recommendation="Collapse each chain to a single direct redirect to the final URL. Each "
                           "extra hop adds latency and dilutes link equity.",
            fix_type=FixType.ASSISTED, fix_category="redirect_chain",
            affected_pages=[p.url for p in multi_hop], impact_score=3, effort_score=2,
        ))
    return findings


def _canonical_findings(base_url: str, pages: list[PageRecord]) -> list[Finding]:
    findings = []
    ok_pages = [p for p in pages if p.status_code == 200]

    missing = [p for p in ok_pages if not p.canonical]
    if missing:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.MEDIUM,
            title="Missing canonical tag",
            description=f"{len(missing)} page(s) have no <link rel=\"canonical\"> tag.",
            evidence="; ".join(p.url for p in missing[:5]),
            recommendation="Add a self-referencing (or correctly cross-referencing, for near-duplicate "
                           "pages) canonical tag to every indexable page to prevent duplicate-content "
                           "signal dilution.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_or_incorrect_canonical",
            affected_pages=[p.url for p in missing], impact_score=3, effort_score=1,
            root_cause_key="missing_canonical_template",
        ))

    mismatched = [p for p in ok_pages if p.canonical and _normalize(p.canonical) != _normalize(p.url)
                  and _same_domain(p.canonical, base_url)]
    if mismatched:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.LOW,
            title="Canonical tag points to a different URL than the page itself",
            description=f"{len(mismatched)} page(s) declare a canonical URL different from their own, "
                        "which may be intentional (parameterized/duplicate pages) or a misconfiguration.",
            evidence="; ".join(f"{p.url} -> canonical: {p.canonical}" for p in mismatched[:5]),
            recommendation="Verify each cross-canonical is intentional; fix any that should be "
                           "self-referencing.",
            fix_type=FixType.ASSISTED, fix_category="missing_or_incorrect_canonical",
            affected_pages=[p.url for p in mismatched], impact_score=2, effort_score=2,
        ))
    return findings


def _indexability_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    noindexed = [p for p in pages if p.meta_robots and "noindex" in p.meta_robots.lower()]
    if noindexed:
        findings.append(Finding(
            category=Category.TECHNICAL, severity=Severity.MEDIUM,
            title="Pages marked noindex",
            description=f"{len(noindexed)} crawled page(s) carry a 'noindex' meta robots directive.",
            evidence="; ".join(f"{p.url} -> {p.meta_robots}" for p in noindexed[:5]),
            recommendation="Confirm each noindex is intentional (e.g. internal search/thank-you pages). "
                           "Remove it from any page that should actually rank.",
            fix_type=FixType.ASSISTED, fix_category=None,
            affected_pages=[p.url for p in noindexed], impact_score=4, effort_score=1,
        ))
    return findings


def _normalize(url: str) -> str:
    return url.rstrip("/").lower()


def _same_domain(url: str, base_url: str) -> bool:
    return urlparse(url).netloc.replace("www.", "") == urlparse(base_url).netloc.replace("www.", "") or \
        not urlparse(url).netloc
