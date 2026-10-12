"""Performance / Core Web Vitals Agent (FR-1.3, FR-1.8).

Produces findings from live PSI data when available, otherwise clearly-labeled assumed/
heuristic findings based on crawl page-weight signals — never fabricated exact metrics.
"""
from __future__ import annotations

from backend.models import Category, Finding, FixType, Severity
from tools.crawler import PageRecord
from tools.psi_client import CoreWebVitals


def run(pages: list[PageRecord], cwv: CoreWebVitals | None,
        base_url: str) -> list[Finding]:
    findings: list[Finding] = []

    if cwv is None or cwv.is_assumed:
        findings.append(Finding(
            category=Category.PERFORMANCE, severity=Severity.MEDIUM,
            title="Core Web Vitals not measured (assumed risks)",
            description=(cwv.source_note if cwv else "No CWV data available for this run."),
            evidence="PSI_API_KEY unset or fixture mode — no live LCP/CLS/INP values.",
            recommendation="Configure PSI_API_KEY for live measurement. In the meantime, audit hero "
                           "images for size/format, add font-display:swap, and defer non-critical JS "
                           "— these are the most common LCP/CLS drivers.",
            fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
            affected_pages=["Site-wide"], impact_score=4, effort_score=3, is_assumed=True,
        ))
    else:
        if cwv.lcp_seconds is not None and cwv.lcp_seconds > 2.5:
            findings.append(Finding(
                category=Category.PERFORMANCE, severity=Severity.HIGH,
                title="Poor Largest Contentful Paint (LCP)",
                description=f"LCP is {cwv.lcp_seconds}s (threshold: ≤2.5s for 'good').",
                evidence=f"PSI measured LCP={cwv.lcp_seconds}s on {base_url}",
                recommendation="Optimize the LCP element (usually the hero image): serve next-gen "
                               "formats (WebP/AVIF), set explicit width/height, preload the hero asset, "
                               "and eliminate render-blocking CSS/JS ahead of it.",
                fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
                affected_pages=[base_url], impact_score=5, effort_score=3,
            ))
        if cwv.cls is not None and cwv.cls > 0.1:
            findings.append(Finding(
                category=Category.PERFORMANCE, severity=Severity.HIGH,
                title="High Cumulative Layout Shift (CLS)",
                description=f"CLS is {cwv.cls} (threshold: ≤0.1 for 'good').",
                evidence=f"PSI measured CLS={cwv.cls} on {base_url}",
                recommendation="Reserve space for images/ads/embeds (width/height or aspect-ratio), "
                               "avoid inserting DOM above existing content, and use font-display:swap "
                               "with size-adjusted fallback fonts.",
                fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
                affected_pages=[base_url], impact_score=4, effort_score=3,
            ))
        if cwv.inp_ms is not None and cwv.inp_ms > 200:
            findings.append(Finding(
                category=Category.PERFORMANCE, severity=Severity.MEDIUM,
                title="High Interaction to Next Paint (INP)",
                description=f"INP is {cwv.inp_ms}ms (threshold: ≤200ms for 'good').",
                evidence=f"PSI measured INP={cwv.inp_ms}ms on {base_url}",
                recommendation="Break up long tasks, defer non-critical third-party scripts, and "
                               "reduce main-thread work on interaction handlers.",
                fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
                affected_pages=[base_url], impact_score=3, effort_score=4,
            ))
        if cwv.performance_score is not None and cwv.performance_score < 50:
            findings.append(Finding(
                category=Category.PERFORMANCE, severity=Severity.HIGH,
                title="Low Lighthouse Performance score",
                description=f"Lighthouse performance score is {cwv.performance_score}/100.",
                evidence=f"PSI performance score={cwv.performance_score}",
                recommendation="Address the highest-weighted Lighthouse opportunities first (LCP "
                               "element, unused JS/CSS, image delivery).",
                fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
                affected_pages=[base_url], impact_score=4, effort_score=3,
            ))

    # Crawl-based heuristics (useful even when PSI is live)
    heavy = [p for p in pages if p.status_code == 200 and p.raw_html_bytes > 500_000]
    if heavy:
        findings.append(Finding(
            category=Category.PERFORMANCE, severity=Severity.MEDIUM,
            title="Large HTML payloads",
            description=f"{len(heavy)} page(s) ship HTML over 500KB uncompressed.",
            evidence="; ".join(f"{p.url} ({p.raw_html_bytes // 1024}KB)" for p in heavy[:5]),
            recommendation="Reduce inline JS/CSS, paginate long lists, and move large data blobs "
                           "out of the initial HTML document.",
            fix_type=FixType.ASSISTED, fix_category="core_web_vitals_issue",
            affected_pages=[p.url for p in heavy], impact_score=3, effort_score=3, is_assumed=True,
        ))

    no_viewport = [p for p in pages if p.status_code == 200]
    # We only flag site-wide mobile risk when CWV is assumed (no live mobile PSI)
    if cwv and cwv.is_assumed and no_viewport:
        findings.append(Finding(
            category=Category.PERFORMANCE, severity=Severity.LOW,
            title="Mobile friendliness not verified",
            description="Mobile viewport / tap-target checks were not run with live mobile PSI data.",
            evidence="Assumed: confirm <meta name=\"viewport\"> is present and tap targets ≥48px.",
            recommendation="Verify viewport meta tag is present site-wide and run a mobile usability "
                           "pass in Search Console or via PSI mobile strategy.",
            fix_type=FixType.MANUAL, fix_category="mobile_usability_issue",
            affected_pages=["Site-wide"], impact_score=2, effort_score=2, is_assumed=True,
        ))

    return findings
