"""Structured Data Agent (Section 5.1).

Validates JSON-LD / Schema.org blocks and proposes missing schema opportunities (FR-1.6).
"""
from __future__ import annotations

from backend.models import Category, Finding, FixType, Severity
from tools.crawler import PageRecord
from tools.schema_validator import validate_json_ld_blocks


def run(pages: list[PageRecord]) -> list[Finding]:
    findings: list[Finding] = []
    ok_pages = [p for p in pages if p.status_code == 200]

    no_schema = [p for p in ok_pages if not p.json_ld_blocks]
    if no_schema:
        findings.append(Finding(
            category=Category.STRUCTURED_DATA, severity=Severity.MEDIUM,
            title="No structured data (JSON-LD) found",
            description=f"{len(no_schema)} of {len(ok_pages)} page(s) have no JSON-LD markup.",
            evidence="; ".join(p.url for p in no_schema[:5]),
            recommendation="Inject JSON-LD for Organization (site-wide), BreadcrumbList (deep pages), "
                           "and Article/Product as appropriate for page type to unlock rich results.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_structured_data",
            affected_pages=[p.url for p in no_schema], impact_score=3, effort_score=2,
            root_cause_key="missing_json_ld_template",
        ))

    for page in ok_pages:
        if not page.json_ld_blocks:
            continue
        result = validate_json_ld_blocks(page.url, page.json_ld_blocks)

        if result.invalid_json_blocks:
            findings.append(Finding(
                category=Category.STRUCTURED_DATA, severity=Severity.HIGH,
                title="Invalid JSON-LD (malformed JSON)",
                description=f"{result.invalid_json_blocks} JSON-LD block(s) on this page are not valid JSON.",
                evidence=f"{page.url}: {result.invalid_json_blocks} unparseable block(s)",
                recommendation="Fix the JSON syntax in the <script type=\"application/ld+json\"> block(s) "
                               "so search engines can consume the schema.",
                fix_type=FixType.AUTO_FIXABLE, fix_category="missing_structured_data",
                affected_pages=[page.url], impact_score=4, effort_score=1,
            ))

        for schema_type, missing_props in result.missing_required_props:
            findings.append(Finding(
                category=Category.STRUCTURED_DATA,
                severity=Severity.MEDIUM,
                title=f"Incomplete {schema_type} schema",
                description=f"{schema_type} markup is missing required property(ies): {', '.join(missing_props)}.",
                evidence=f"{page.url}: {schema_type} missing {missing_props}",
                recommendation=f"Add the missing properties ({', '.join(missing_props)}) to the "
                               f"{schema_type} JSON-LD so the type qualifies for rich results.",
                fix_type=FixType.AUTO_FIXABLE, fix_category="missing_structured_data",
                affected_pages=[page.url], impact_score=3, effort_score=1,
            ))

    # Site-wide opportunity: Organization schema if none of the crawled pages have it
    all_types: set[str] = set()
    for page in ok_pages:
        if page.json_ld_blocks:
            result = validate_json_ld_blocks(page.url, page.json_ld_blocks)
            all_types |= result.types_present

    if "Organization" not in all_types and ok_pages:
        findings.append(Finding(
            category=Category.STRUCTURED_DATA, severity=Severity.LOW,
            title="Missing Organization schema (site-wide opportunity)",
            description="No Organization JSON-LD found on any crawled page.",
            evidence="Schema types present site-wide: " + (", ".join(sorted(all_types)) or "none"),
            recommendation="Add Organization schema (name, url, logo) to the shared layout template "
                           "to establish brand entity signals for knowledge panel eligibility.",
            fix_type=FixType.AUTO_FIXABLE, fix_category="missing_structured_data",
            affected_pages=["Site-wide"], impact_score=2, effort_score=1,
            root_cause_key="missing_organization_schema",
        ))

    if "BreadcrumbList" not in all_types and ok_pages:
        deep = [p for p in ok_pages if p.url.count("/") > 3]
        if deep:
            findings.append(Finding(
                category=Category.STRUCTURED_DATA, severity=Severity.LOW,
                title="Missing BreadcrumbList schema",
                description="No BreadcrumbList JSON-LD found; deep pages cannot earn breadcrumb rich results.",
                evidence=f"{len(deep)} deep page(s) without BreadcrumbList; example: {deep[0].url}",
                recommendation="Inject BreadcrumbList JSON-LD on all nested pages reflecting the nav hierarchy.",
                fix_type=FixType.AUTO_FIXABLE, fix_category="missing_structured_data",
                affected_pages=[p.url for p in deep[:10]], impact_score=2, effort_score=2,
            ))

    return findings
