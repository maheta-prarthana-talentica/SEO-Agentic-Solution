"""Reporting Agent (Section 5.1).

Compiles the human-readable audit report in the exact format specified by the Phase-1
SEO Audit Agent prompt: Summary, Detailed Findings, Prioritization, Top Recommendations,
Phase 2 Readiness — ending with the Phase-2 CTA.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.models import AuditRun, Finding, FixType
from agents.prioritization import (
    apply_fix_category_tags,
    compute_category_scores,
    compute_overall_score,
    deduplicate_by_root_cause,
    group_by_quadrant,
    rank_findings,
)
from tools.llm_client import LLMClient
from tools.logging_utils import TraceLogger

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def compile_report(
    run: AuditRun,
    all_findings: list[Finding],
    llm: LLMClient | None = None,
    trace: TraceLogger | None = None,
    pr_url: str | None = None,
) -> tuple[AuditRun, str]:
    """Returns (updated AuditRun, markdown report). Also writes JSON+MD under reports/."""
    findings = apply_fix_category_tags(all_findings)
    findings = deduplicate_by_root_cause(findings)
    findings = rank_findings(findings)

    category_scores = compute_category_scores(findings)
    overall = compute_overall_score(category_scores)

    from backend.models import Category, CategoryScore

    run.findings = findings
    run.overall_score = overall
    run.category_scores = [
        CategoryScore(
            category=Category(k),
            score=v,
            findings_count=sum(1 for f in findings if f.category.value == k),
        )
        for k, v in category_scores.items()
    ]
    run.completed_at = datetime.now(timezone.utc)
    if llm:
        run.llm_tokens_used = llm.usage.total

    strengths, weaknesses = _strengths_weaknesses(findings, category_scores)
    narrative = None
    if llm:
        narrative = llm.narrate_findings({
            "overall_score": overall,
            "category_scores": category_scores,
            "finding_count": len(findings),
            "top_titles": [f.title for f in findings[:5]],
        })

    md = _render_markdown(
        run=run,
        findings=findings,
        strengths=strengths,
        weaknesses=weaknesses,
        narrative=narrative,
        pr_url=pr_url,
    )

    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / f"{run.run_id}.md").write_text(md, encoding="utf-8")
    (REPORTS_DIR / f"{run.run_id}.json").write_text(
        run.model_dump_json(indent=2), encoding="utf-8"
    )

    if trace:
        trace.log("ReportingAgent", "report_written",
                  {"run_id": run.run_id, "findings": len(findings), "score": overall})

    return run, md


def _strengths_weaknesses(
    findings: list[Finding], category_scores: dict[str, int]
) -> tuple[list[str], list[str]]:
    strengths = [f"{cat.replace('-', ' ').title()} looks healthy (score {score}/100)"
                 for cat, score in category_scores.items() if score >= 80]
    if not strengths:
        strengths = ["Crawl completed successfully and produced evidence-backed findings."]

    weaknesses = [f.title for f in findings if f.severity.value in ("critical", "high")][:5]
    if not weaknesses:
        weaknesses = [f.title for f in findings[:3]] or ["No major weaknesses detected."]
    return strengths, weaknesses


def _render_markdown(
    run: AuditRun,
    findings: list[Finding],
    strengths: list[str],
    weaknesses: list[str],
    narrative: str | None,
    pr_url: str | None,
) -> str:
    lines: list[str] = []
    lines.append(f"# SEO Audit Report — {run.target_url}")
    lines.append("")
    lines.append(f"**Run ID:** `{run.run_id}`  ")
    lines.append(f"**Pages crawled:** {len(run.pages_crawled)}  ")
    lines.append(f"**Generated:** {run.completed_at.isoformat() if run.completed_at else 'n/a'}")
    lines.append("")

    # 1. SUMMARY
    lines.append("## 1. SUMMARY")
    lines.append("")
    lines.append(f"- **Overall SEO score:** {run.overall_score}/100")
    lines.append("- **Category scores:**")
    for cs in run.category_scores:
        lines.append(f"  - {cs.category.value}: {cs.score}/100 ({cs.findings_count} finding(s))")
    lines.append("")
    if narrative:
        lines.append(narrative.strip())
        lines.append("")
    lines.append("**Key strengths**")
    for s in strengths:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("**Key weaknesses**")
    for w in weaknesses:
        lines.append(f"- {w}")
    lines.append("")

    # 2. DETAILED FINDINGS
    lines.append("## 2. DETAILED FINDINGS")
    lines.append("")
    if not findings:
        lines.append("_No issues detected._")
        lines.append("")
    for f in findings:
        lines.append(f"### {f.id}: {f.title}")
        lines.append("")
        lines.append(f"- **Category:** {f.category.value.replace('-', ' ').title()}")
        lines.append(f"- **Severity:** {f.severity.display}")
        pages = ", ".join(f.affected_pages[:8]) if f.affected_pages else "Site-wide"
        if len(f.affected_pages) > 8:
            pages += f" (+{len(f.affected_pages) - 8} more)"
        lines.append(f"- **Affected Pages:** {pages}")
        lines.append(f"- **Issue Description:** {f.description}")
        lines.append(f"- **Evidence:** {f.evidence}")
        if f.is_assumed:
            lines.append("- **Note:** Evidence / metrics are assumed (live data unavailable).")
        lines.append(f"- **Recommended Fix:** {f.recommendation}")
        lines.append(f"- **Fix Type:** {_fix_type_display(f.fix_type)}")
        lines.append("")

    # 3. PRIORITIZATION
    lines.append("## 3. PRIORITIZATION")
    lines.append("")
    groups = group_by_quadrant(findings)
    lines.append("### High Impact / Low Effort (Quick Wins)")
    lines.extend(_bullet_findings(groups.get("quick_win", [])))
    lines.append("")
    lines.append("### High Impact / High Effort")
    lines.extend(_bullet_findings(groups.get("high_impact_high_effort", [])))
    lines.append("")
    lines.append("### Low Impact")
    lines.extend(_bullet_findings(groups.get("low_impact", [])))
    lines.append("")

    # 4. TOP RECOMMENDATIONS
    lines.append("## 4. TOP RECOMMENDATIONS")
    lines.append("")
    top = findings[:10]
    for i, f in enumerate(top, 1):
        lines.append(
            f"{i}. **{f.title}** (impact {f.impact_score}/5, effort {f.effort_score}/5, "
            f"{_fix_type_display(f.fix_type)}) — {f.recommendation}"
        )
    if not top:
        lines.append("_No recommendations._")
    lines.append("")

    # 5. PHASE 2 READINESS
    lines.append("## 5. PHASE 2 READINESS")
    lines.append("")
    auto = [f for f in findings if f.fix_type == FixType.AUTO_FIXABLE]
    assisted = [f for f in findings if f.fix_type == FixType.ASSISTED]
    manual = [f for f in findings if f.fix_type == FixType.MANUAL]

    lines.append("### Safe for automated code fixes")
    if auto:
        for f in auto:
            lines.append(f"- `{f.id}` {f.title}" + (f" → `{f.mapped_file}`" if f.mapped_file else ""))
    else:
        lines.append("- None identified in this run.")
    lines.append("")
    lines.append("### Require assisted / review")
    if assisted:
        for f in assisted:
            lines.append(f"- `{f.id}` {f.title}")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("### Require manual intervention")
    if manual:
        for f in manual:
            lines.append(f"- `{f.id}` {f.title}")
    else:
        lines.append("- None.")
    lines.append("")

    if pr_url:
        lines.append(f"**Phase 2 succeeded — remediation PR:** {pr_url}")
        lines.append("")
    elif getattr(run, "phase2_status", None) == "failed":
        lines.append(
            f"**Phase 2 failed:** {getattr(run, 'phase2_message', None) or 'see run errors'}"
        )
        if getattr(run, "branch_name", None):
            lines.append(f"- Branch created (no PR): `{run.branch_name}`")
        lines.append("")
    elif getattr(run, "phase2_status", None) == "skipped":
        lines.append(
            f"**Phase 2 skipped:** {getattr(run, 'phase2_message', None) or 'credentials missing'}"
        )
        lines.append("")

    lines.append('Do you want to proceed to Phase 2 (GitHub-based code fixes)?')
    lines.append("")
    return "\n".join(lines)


def _fix_type_display(ft: FixType) -> str:
    return {
        FixType.AUTO_FIXABLE: "Auto-fixable",
        FixType.ASSISTED: "Assisted",
        FixType.MANUAL: "Manual",
    }[ft]


def _bullet_findings(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["- _None_"]
    return [f"- `{f.id}` **{f.title}** (severity: {f.severity.display}, "
            f"priority score: {f.priority_score})" for f in findings]
