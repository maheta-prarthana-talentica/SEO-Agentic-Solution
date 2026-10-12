"""Content & On-Page Agent (Section 5.1).

Assesses titles, meta tags, headings, alt text, internal linking, keyword relevance,
readability -- FR-1.4, FR-1.7, FR-1.8 (on-page portion).

Untrusted-input note: page body text extracted by the crawler is passed to
`tools/llm_client.py::score_page_content` only through `sanitize_untrusted_text` and is
never used to build a system prompt -- see that module's docstring.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from backend.models import Category, Finding, FixType, Severity
from tools.crawler import PageRecord
from tools.llm_client import LLMClient

TITLE_MIN, TITLE_MAX = 15, 60
META_DESC_MIN, META_DESC_MAX = 50, 160
THIN_CONTENT_WORD_THRESHOLD = 300


def run_onpage(pages: list[PageRecord]) -> list[Finding]:
    ok_pages = [p for p in pages if p.status_code == 200]
    findings: list[Finding] = []
    findings.extend(_title_findings(ok_pages))
    findings.extend(_meta_description_findings(ok_pages))
    findings.extend(_heading_findings(ok_pages))
    findings.extend(_alt_text_findings(ok_pages))
    findings.extend(_internal_linking_findings(ok_pages))
    return findings


def run_content_quality(pages: list[PageRecord], llm: LLMClient | None = None) -> list[Finding]:
    ok_pages = [p for p in pages if p.status_code == 200]
    findings: list[Finding] = []
    findings.extend(_thin_content_findings(ok_pages))
    findings.extend(_duplicate_content_findings(ok_pages))
    if llm is not None:
        findings.extend(_llm_readability_findings(ok_pages[:5], llm))  # cap LLM calls per run
    return findings


# -- On-page ------------------------------------------------------------------------------

def _title_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    missing = [p for p in pages if not p.title]
    if missing:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.HIGH, title="Missing title tag",
            description=f"{len(missing)} page(s) have no <title> element.",
            evidence="; ".join(p.url for p in missing[:5]),
            recommendation="Add a unique, descriptive title (15-60 characters) to every page, "
                           "front-loading the primary keyword.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_or_duplicate_meta_title",
            affected_pages=[p.url for p in missing], impact_score=5, effort_score=1,
            root_cause_key="missing_title_template",
        ))

    bad_length = [p for p in pages if p.title and not (TITLE_MIN <= len(p.title) <= TITLE_MAX)]
    if bad_length:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.MEDIUM, title="Title tag length out of range",
            description=f"{len(bad_length)} page(s) have a title shorter than {TITLE_MIN} or longer "
                        f"than {TITLE_MAX} characters, risking truncation in search results.",
            evidence="; ".join(f"{p.url} ({len(p.title)} chars)" for p in bad_length[:5]),
            recommendation=f"Rewrite titles to fall within {TITLE_MIN}-{TITLE_MAX} characters while "
                           "keeping them descriptive and keyword-relevant.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_or_duplicate_meta_title",
            affected_pages=[p.url for p in bad_length], impact_score=2, effort_score=1,
        ))

    findings.extend(_duplicate_field_finding(
        pages, field="title", label="title tags", severity=Severity.HIGH,
        fix_category="missing_or_duplicate_meta_title", impact_score=4,
    ))
    return findings


def _meta_description_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    missing = [p for p in pages if not p.meta_description]
    if missing:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.MEDIUM, title="Missing meta description",
            description=f"{len(missing)} page(s) have no meta description.",
            evidence="; ".join(p.url for p in missing[:5]),
            recommendation=f"Write a unique, compelling meta description ({META_DESC_MIN}-"
                           f"{META_DESC_MAX} characters) per page to improve SERP click-through rate.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_or_duplicate_meta_description",
            affected_pages=[p.url for p in missing], impact_score=3, effort_score=1,
            root_cause_key="missing_meta_description_template",
        ))

    bad_length = [p for p in pages if p.meta_description
                  and not (META_DESC_MIN <= len(p.meta_description) <= META_DESC_MAX)]
    if bad_length:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.LOW, title="Meta description length out of range",
            description=f"{len(bad_length)} page(s) have a meta description outside the "
                        f"{META_DESC_MIN}-{META_DESC_MAX} character sweet spot.",
            evidence="; ".join(f"{p.url} ({len(p.meta_description)} chars)" for p in bad_length[:5]),
            recommendation="Rewrite to fit the recommended length so it isn't truncated in search results.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_or_duplicate_meta_description",
            affected_pages=[p.url for p in bad_length], impact_score=1, effort_score=1,
        ))

    findings.extend(_duplicate_field_finding(
        pages, field="meta_description", label="meta descriptions", severity=Severity.MEDIUM,
        fix_category="missing_or_duplicate_meta_description", impact_score=3,
    ))
    return findings


def _duplicate_field_finding(pages: list[PageRecord], field: str, label: str, severity: Severity,
                              fix_category: str, impact_score: int) -> list[Finding]:
    values: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        value = getattr(p, field)
        if value:
            values[value.strip().lower()].append(p.url)
    duplicates = {v: urls for v, urls in values.items() if len(urls) > 1}
    if not duplicates:
        return []
    total_affected = sum(len(urls) for urls in duplicates.values())
    example_value, example_urls = next(iter(duplicates.items()))
    return [Finding(
        category=Category.ON_PAGE, severity=severity, title=f"Duplicate {label} across pages",
        description=f"{len(duplicates)} distinct {label} value(s) are reused across {total_affected} "
                    "pages combined, diluting relevance signals for each page.",
        evidence=f"Example: \"{example_value[:80]}\" is used on {len(example_urls)} pages "
                 f"({example_urls[:3]}...).",
        recommendation=f"Generate a unique {label.rstrip('s')} per page reflecting that page's specific "
                       "content/keyword focus.",
        fix_type=FixType.AUTO_FIXABLE, fix_category=fix_category,
        affected_pages=[u for urls in duplicates.values() for u in urls], impact_score=impact_score,
        effort_score=2, root_cause_key=f"duplicate_{field}_template",
    )]


def _heading_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    no_h1 = [p for p in pages if not any(tag == "h1" for tag, _ in p.headings)]
    if no_h1:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.HIGH, title="Missing H1",
            description=f"{len(no_h1)} page(s) have no H1 heading.",
            evidence="; ".join(p.url for p in no_h1[:5]),
            recommendation="Add exactly one H1 per page that clearly states the page topic and "
                           "contains the primary keyword.",
            fix_type=FixType.ASSISTED, fix_category="heading_hierarchy_issue",
            affected_pages=[p.url for p in no_h1], impact_score=4, effort_score=2,
            root_cause_key="missing_h1_template",
        ))

    multi_h1 = [p for p in pages if sum(1 for tag, _ in p.headings if tag == "h1") > 1]
    if multi_h1:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.LOW, title="Multiple H1 tags on one page",
            description=f"{len(multi_h1)} page(s) contain more than one H1.",
            evidence="; ".join(f"{p.url} ({sum(1 for t,_ in p.headings if t=='h1')} H1s)"
                                for p in multi_h1[:5]),
            recommendation="Consolidate to a single H1; demote the others to H2/H3 as appropriate.",
            fix_type=FixType.ASSISTED, fix_category="heading_hierarchy_issue",
            affected_pages=[p.url for p in multi_h1], impact_score=2, effort_score=2,
        ))

    skipped = [p for p in pages if _has_skipped_level(p.headings)]
    if skipped:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.LOW, title="Skipped heading levels",
            description=f"{len(skipped)} page(s) skip a heading level (e.g. H1 -> H3 with no H2).",
            evidence="; ".join(f"{p.url}: {[t for t,_ in p.headings]}" for p in skipped[:3]),
            recommendation="Restructure headings to descend one level at a time for a clear document "
                           "outline (accessibility + SEO benefit).",
            fix_type=FixType.ASSISTED, fix_category="heading_hierarchy_issue",
            affected_pages=[p.url for p in skipped], impact_score=1, effort_score=2,
        ))
    return findings


def _has_skipped_level(headings: list[tuple[str, str]]) -> bool:
    levels = [int(tag[1]) for tag, _ in headings]
    seen_max = 0
    for level in levels:
        if level > seen_max + 1 and seen_max != 0:
            return True
        seen_max = max(seen_max, level)
    return False


def _alt_text_findings(pages: list[PageRecord]) -> list[Finding]:
    total_images = sum(len(p.images) for p in pages)
    missing_alt = [(p.url, src) for p in pages for src, alt in p.images if not alt or not alt.strip()]
    if not missing_alt:
        return []
    pct = round(100 * len(missing_alt) / max(total_images, 1))
    severity = Severity.HIGH if pct > 50 else Severity.MEDIUM
    return [Finding(
        category=Category.ON_PAGE, severity=severity, title="Missing image alt text",
        description=f"{len(missing_alt)} of {total_images} images ({pct}%) across the crawl have no "
                    "alt attribute or an empty one.",
        evidence="; ".join(f"{url} -> {src}" for url, src in missing_alt[:5]),
        recommendation="Add descriptive alt text generated from image filename/context and surrounding "
                       "copy for every meaningful image; use alt=\"\" only for purely decorative images.",
        fix_type=FixType.AUTO_FIXABLE, fix_category="missing_image_alt_text",
        affected_pages=list({u for u, _ in missing_alt}), impact_score=3, effort_score=2,
        root_cause_key="missing_alt_text_sitewide",
    )]


def _internal_linking_findings(pages: list[PageRecord]) -> list[Finding]:
    findings = []
    inbound_counts = Counter()
    for p in pages:
        for link in p.internal_links:
            inbound_counts[link.rstrip("/")] += 1

    orphans = [p for p in pages if inbound_counts.get(p.url.rstrip("/"), 0) == 0]
    # The crawl entry point is trivially "orphaned" by this metric; exclude the shortest URL (home page).
    if orphans and len(orphans) < len(pages):
        orphans = [p for p in orphans if p.url != pages[0].url]
    if orphans:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.MEDIUM, title="Orphan pages (no internal inlinks)",
            description=f"{len(orphans)} crawled page(s) receive no internal links from any other "
                        "crawled page, relying entirely on the sitemap/external links for discovery.",
            evidence="; ".join(p.url for p in orphans[:5]),
            recommendation="Add contextual internal links (nav, related-content, breadcrumbs) pointing "
                           "to these pages from relevant hub/category pages.",
            fix_type=FixType.ASSISTED, fix_category=None,
            affected_pages=[p.url for p in orphans], impact_score=3, effort_score=3,
        ))

    thin_links = [p for p in pages if len(p.internal_links) < 2]
    if thin_links:
        findings.append(Finding(
            category=Category.ON_PAGE, severity=Severity.LOW, title="Very few internal links on page",
            description=f"{len(thin_links)} page(s) contain fewer than 2 internal links, limiting "
                        "link-equity flow and crawl paths deeper into the site.",
            evidence="; ".join(p.url for p in thin_links[:5]),
            recommendation="Add relevant internal links (related articles, category/product cross-"
                           "links) to improve crawlability and topical authority signals.",
            fix_type=FixType.ASSISTED, fix_category=None,
            affected_pages=[p.url for p in thin_links], impact_score=2, effort_score=2,
        ))
    return findings


# -- Content quality -----------------------------------------------------------------------

def _thin_content_findings(pages: list[PageRecord]) -> list[Finding]:
    thin = [p for p in pages if p.word_count < THIN_CONTENT_WORD_THRESHOLD]
    if not thin:
        return []
    return [Finding(
        category=Category.CONTENT, severity=Severity.MEDIUM, title="Thin content",
        description=f"{len(thin)} page(s) have fewer than {THIN_CONTENT_WORD_THRESHOLD} words of body "
                    "content, likely insufficient to demonstrate topical depth to search engines.",
        evidence="; ".join(f"{p.url} (~{p.word_count} words)" for p in thin[:5]),
        recommendation="Expand thin pages with substantive, unique content addressing user intent, or "
                       "consolidate near-duplicate thin pages into one comprehensive page.",
        fix_type=FixType.MANUAL, fix_category="thin_or_duplicate_content",
        affected_pages=[p.url for p in thin], impact_score=3, effort_score=4,
    )]


def _duplicate_content_findings(pages: list[PageRecord]) -> list[Finding]:
    """Heuristic duplicate detection: pages with identical title AND near-identical word
    count are flagged as likely duplicate/boilerplate-only content. A full page-diff/
    shingling comparison is a natural Phase 2 enhancement once repo templates are indexed.
    """
    buckets: dict[tuple[str, int], list[str]] = defaultdict(list)
    for p in pages:
        if p.title and p.word_count:
            bucket_key = (p.title.strip().lower(), round(p.word_count / 20))
            buckets[bucket_key].append(p.url)

    duplicate_groups = [urls for urls in buckets.values() if len(urls) > 1]
    if not duplicate_groups:
        return []
    total = sum(len(g) for g in duplicate_groups)
    return [Finding(
        category=Category.CONTENT, severity=Severity.MEDIUM, title="Likely duplicate content",
        description=f"{len(duplicate_groups)} group(s) totaling {total} pages share the same title and "
                    "near-identical word count, suggesting duplicated or templated-only content.",
        evidence=f"Example group: {duplicate_groups[0]}",
        recommendation="Differentiate each page's content meaningfully, or canonicalize/consolidate "
                       "true duplicates to a single indexable URL.",
        fix_type=FixType.MANUAL, fix_category="thin_or_duplicate_content",
        affected_pages=[u for g in duplicate_groups for u in g], impact_score=3, effort_score=4,
        is_assumed=True,
    )]


def _llm_readability_findings(pages: list[PageRecord], llm: LLMClient) -> list[Finding]:
    findings = []
    for p in pages:
        try:
            result = llm.score_page_content(
                url=p.url,
                title=p.title or "",
                meta_description=p.meta_description or "",
                heading_sequence=[h for _, h in p.headings],
                page_text="",  # body text not retained post-crawl
            )
        except Exception:  # noqa: BLE001 — never let one LLM page fail the whole audit
            continue
        if not result or not isinstance(result, dict):
            continue

        raw_issues = result.get("issues") or []
        if not isinstance(raw_issues, list):
            raw_issues = [raw_issues]

        suggestions = result.get("rewrite_suggestions") or []
        if isinstance(suggestions, str):
            suggestion_text = suggestions
        elif isinstance(suggestions, list):
            suggestion_text = "; ".join(
                s if isinstance(s, str) else str(s.get("suggestion", s))
                for s in suggestions
            )
        else:
            suggestion_text = str(suggestions)

        for issue in raw_issues:
            if isinstance(issue, str):
                issue_text, evidence = issue, ""
            elif isinstance(issue, dict):
                issue_text = str(issue.get("issue") or issue.get("title") or "flagged issue")
                evidence = str(issue.get("evidence") or "")
            else:
                continue
            findings.append(Finding(
                category=Category.CONTENT, severity=Severity.LOW,
                title=f"Content quality: {issue_text[:120]}",
                description=issue_text,
                evidence=evidence or f"LLM content review for {p.url}",
                recommendation=suggestion_text or "Revise per LLM guidance.",
                fix_type=FixType.MANUAL, fix_category="thin_or_duplicate_content",
                affected_pages=[p.url], impact_score=2, effort_score=3,
            ))
    return findings
