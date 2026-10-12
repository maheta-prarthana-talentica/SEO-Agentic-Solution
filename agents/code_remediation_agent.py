"""Code Remediation Agent (Phase 3 / Section 7.4).

Generates minimal diffs for auto-fixable findings. Every proposed path is checked
against the hard denylist before any LLM call or template edit (Section 6.4 / 11).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.models import Finding, FindingStatus, FixType
from tools.diff_utils import (
    diff_within_cap,
    enforce_denylist,
    load_denylist,
    make_unified_diff,
)
from tools.llm_client import LLMClient
from tools.logging_utils import TraceLogger
from tools.robots_sitemap import generate_corrected_robots_txt, generate_corrected_sitemap_xml


def run(
    findings: list[Finding],
    repo_path: Path | str | None,
    conventions: dict,
    *,
    llm: LLMClient | None = None,
    trace: TraceLogger | None = None,
) -> list[dict[str, Any]]:
    """Returns a list of proposed fix dicts:
    {finding_id, commit_scope, files: {path: new_content}, diff, rationale, blocked}.
    """
    if repo_path is None:
        if trace:
            trace.log("CodeRemediationAgent", "skipped_no_repo", level="warning")
        return []

    repo_path = Path(repo_path)
    cfg = load_denylist()
    proposals: list[dict[str, Any]] = []

    # Sitemap/robots can be fixed without a mapped template file.
    auto_findings = [
        f for f in findings
        if f.fix_type == FixType.AUTO_FIXABLE
        and (f.mapped_file or f.fix_category == "sitemap_or_robots_error")
    ]
    for finding in auto_findings:
        target = finding.mapped_file or ""
        if target:
            denied = enforce_denylist([target], cfg)
            if denied:
                finding.status = FindingStatus.BLOCKED_BY_DENYLIST
                finding.fix_type = FixType.MANUAL
                if trace:
                    trace.log("CodeRemediationAgent", "blocked_by_denylist",
                              {"path": target}, finding_id=finding.id, level="warning")
                proposals.append({
                    "finding_id": finding.id,
                    "blocked": True,
                    "reason": f"denylist matched: {denied}",
                    "commit_scope": finding.fix_category,
                    "files": {},
                    "diff": "",
                    "rationale": "Blocked by hard denylist gate.",
                })
                continue

        proposal = _generate_fix(finding, repo_path, conventions, llm, trace)
        if proposal is None:
            if trace:
                trace.log("CodeRemediationAgent", "no_patch_generated",
                          {"category": finding.fix_category, "mapped": finding.mapped_file},
                          finding_id=finding.id, level="warning")
            continue

        # Diff-size cap (Section 6.4)
        file_count = len(proposal.get("files") or {})
        if file_count == 0:
            # Never hand GitHub an empty files payload (creates branch, no PR).
            if trace:
                trace.log("CodeRemediationAgent", "empty_files_skipped",
                          {"category": finding.fix_category},
                          finding_id=finding.id, level="warning")
            continue
        if not diff_within_cap(proposal.get("diff", ""), file_count, cfg):
            finding.fix_type = FixType.MANUAL
            if trace:
                trace.log("CodeRemediationAgent", "diff_too_large",
                          {"lines": len(proposal.get("diff", "").splitlines()),
                           "files": file_count}, finding_id=finding.id, level="warning")
            proposal["blocked"] = True
            proposal["reason"] = "Diff exceeded size cap — downgraded to recommendation-only."
        else:
            finding.status = FindingStatus.FIX_GENERATED
            proposal["blocked"] = False

        proposals.append(proposal)
        if trace:
            trace.log("CodeRemediationAgent", "fix_proposed",
                      {"scope": proposal.get("commit_scope"),
                       "blocked": proposal.get("blocked"),
                       "files": list((proposal.get("files") or {}).keys())},
                      finding_id=finding.id)

    # Guarantee at least one commit artifact when auto-fixables exist but no patches
    # could be produced for this framework — still open a reviewable PR with notes.
    if not any(not p.get("blocked") and p.get("files") for p in proposals):
        auto_open = [f for f in findings if f.fix_type == FixType.AUTO_FIXABLE]
        if auto_open:
            notes = _build_findings_notes(auto_open)
            path = "seo-agent/PHASE2_FINDINGS.md"
            proposals.append({
                "finding_id": auto_open[0].id,
                "commit_scope": "seo-report",
                "files": {path: notes},
                "diff": make_unified_diff(path, "", notes),
                "rationale": "No code-level patch could be applied automatically; "
                            "opened a findings report for engineer review.",
                "blocked": False,
            })
            if trace:
                trace.log("CodeRemediationAgent", "fallback_notes_commit",
                          {"path": path, "findings": len(auto_open)})

    return proposals


def _build_findings_notes(findings: list[Finding]) -> str:
    lines = [
        "# SEO Agent — Phase 2 findings (auto-fixable)",
        "",
        "The agent could not safely patch application templates for every finding.",
        "Please apply these manually or extend the remediation templates.",
        "",
    ]
    for f in findings:
        lines += [
            f"## {f.id}: {f.title}",
            f"- Category: {f.category.value}",
            f"- Mapped file: `{f.mapped_file or 'n/a'}`",
            f"- Evidence: {f.evidence}",
            f"- Recommendation: {f.recommendation}",
            "",
        ]
    return "\n".join(lines) + "\n"


def _generate_fix(
    finding: Finding,
    repo_path: Path,
    conventions: dict,
    llm: LLMClient | None,
    trace: TraceLogger | None,
) -> dict[str, Any] | None:
    # Prefer deterministic template fixers for well-known categories; LLM as enrichment.
    cat = finding.fix_category or ""

    if cat == "sitemap_or_robots_error":
        return _fix_sitemap_robots(finding, repo_path, conventions)

    # Deterministic templates first (HTML / common patterns)
    template: dict[str, Any] | None = None
    if cat in {"missing_or_duplicate_meta_title", "missing_or_duplicate_meta_description",
               "missing_or_incorrect_canonical"}:
        template = _fix_meta_tags(finding, repo_path, conventions)
    elif cat == "missing_image_alt_text":
        template = _fix_alt_text(finding, repo_path)
    elif cat == "missing_structured_data":
        template = _fix_structured_data(finding, repo_path, conventions)
    elif cat == "broken_internal_link":
        template = _fix_broken_links(finding, repo_path)

    if template and template.get("files"):
        return template

    # LLM only if it returns concrete file contents (never empty files payload)
    if llm is not None and finding.mapped_file:
        candidate = repo_path / finding.mapped_file
        old = candidate.read_text(encoding="utf-8", errors="ignore") if candidate.exists() else ""
        result = llm.generate_fix_diff(
            finding_json=finding.model_dump(mode="json"),
            candidate_files={finding.mapped_file: old},
            repo_conventions=conventions,
            denylist_patterns=load_denylist().paths,
        )
        if result and not result.get("blocked_by_denylist"):
            new_content = result.get("new_content") or result.get("updated_content")
            files = result.get("files") if isinstance(result.get("files"), dict) else {}
            if new_content and finding.mapped_file:
                files = {**files, finding.mapped_file: new_content}
            if files:
                diffs = []
                for path, new in files.items():
                    prev = (repo_path / path).read_text(encoding="utf-8", errors="ignore") \
                        if (repo_path / path).exists() else ""
                    diffs.append(make_unified_diff(path, prev, new))
                return {
                    "finding_id": finding.id,
                    "commit_scope": result.get("commit_scope") or cat or "seo-fix",
                    "files": files,
                    "diff": "\n".join(diffs),
                    "rationale": result.get("rationale") or finding.recommendation,
                    "llm_generated": True,
                }

    return template


def _public_dir(repo_path: Path, conventions: dict) -> Path:
    name = conventions.get("public_dir") or "public"
    d = repo_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fix_sitemap_robots(finding: Finding, repo_path: Path, conventions: dict) -> dict[str, Any]:
    public = _public_dir(repo_path, conventions)
    files: dict[str, str] = {}
    # Derive a base URL from affected pages or a placeholder
    base = "https://example.com"
    if finding.affected_pages and finding.affected_pages[0] != "Site-wide":
        parsed = urlparse(finding.affected_pages[0])
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"

    blob = " ".join(
        filter(
            None,
            [
                finding.title,
                finding.description,
                finding.evidence,
                finding.recommendation,
                finding.fix_category or "",
            ],
        )
    ).lower()

    if "robots" in blob or "robot" in blob:
        rel = f"{public.relative_to(repo_path).as_posix()}/robots.txt"
        if (repo_path / "robots.txt").exists():
            rel = "robots.txt"
        files[rel] = generate_corrected_robots_txt(base)

    if "sitemap" in blob:
        urls = [u for u in finding.affected_pages if u.startswith("http")] or [base + "/"]
        rel = f"{public.relative_to(repo_path).as_posix()}/sitemap.xml"
        if (repo_path / "sitemap.xml").exists():
            rel = "sitemap.xml"
        files[rel] = generate_corrected_sitemap_xml(urls)

    if not files:
        # Generic: write both
        files[f"{public.relative_to(repo_path).as_posix()}/robots.txt"] = generate_corrected_robots_txt(base)
        files[f"{public.relative_to(repo_path).as_posix()}/sitemap.xml"] = generate_corrected_sitemap_xml([base + "/"])

    diffs = []
    for path, new in files.items():
        old = (repo_path / path).read_text(encoding="utf-8") if (repo_path / path).exists() else ""
        diffs.append(make_unified_diff(path, old, new))
    return {
        "finding_id": finding.id,
        "commit_scope": "sitemap-robots",
        "files": files,
        "diff": "\n".join(diffs),
        "rationale": f"Resolves {finding.id}: regenerated robots.txt/sitemap.xml per FR-1.5.",
    }


def _fix_meta_tags(finding: Finding, repo_path: Path, conventions: dict) -> dict[str, Any] | None:
    path = finding.mapped_file
    if not path:
        return None
    full = repo_path / path
    if not full.exists():
        return None
    old = full.read_text(encoding="utf-8")
    new = old
    page_label = finding.affected_pages[0] if finding.affected_pages else "page"

    if finding.fix_category == "missing_or_duplicate_meta_title" and "<title" not in old.lower():
        snippet = f"<title>TODO: unique title for {page_label}</title>\n"
        new = _inject_in_head(old, snippet)
    if finding.fix_category == "missing_or_duplicate_meta_description" and 'name="description"' not in old:
        snippet = (
            f'<meta name="description" content="TODO: unique meta description for {page_label}">\n'
        )
        new = _inject_in_head(new, snippet)
    if finding.fix_category == "missing_or_incorrect_canonical" and "rel=\"canonical\"" not in old:
        canon = page_label if page_label.startswith("http") else "https://example.com/"
        snippet = f'<link rel="canonical" href="{canon}">\n'
        new = _inject_in_head(new, snippet)

    if new == old:
        return None
    return {
        "finding_id": finding.id,
        "commit_scope": "meta-tags",
        "files": {path: new},
        "diff": make_unified_diff(path, old, new),
        "rationale": f"Resolves {finding.id}: ensure title/description/canonical tags are present.",
    }


def _fix_alt_text(finding: Finding, repo_path: Path) -> dict[str, Any] | None:
    path = finding.mapped_file
    if not path:
        return None
    full = repo_path / path
    if not full.exists():
        return None
    import re
    old = full.read_text(encoding="utf-8")

    def repl(match: re.Match) -> str:
        tag = match.group(0)
        if "alt=" in tag:
            return tag
        src = re.search(r'src=["\']([^"\']+)["\']', tag)
        name = Path(src.group(1)).stem.replace("-", " ").replace("_", " ") if src else "image"
        return tag[:-1] + f' alt="{name}">'

    new = re.sub(r"<img\b[^>]*>", repl, old, flags=re.I)
    if new == old:
        return None
    return {
        "finding_id": finding.id,
        "commit_scope": "alt-text",
        "files": {path: new},
        "diff": make_unified_diff(path, old, new),
        "rationale": f"Resolves {finding.id}: added descriptive alt text to <img> tags missing alt.",
    }


def _fix_structured_data(finding: Finding, repo_path: Path, conventions: dict) -> dict[str, Any] | None:
    path = finding.mapped_file or (conventions.get("layout_files") or [None])[0]
    if not path:
        return None
    full = repo_path / path
    if not full.exists():
        return None
    old = full.read_text(encoding="utf-8")
    if "application/ld+json" in old and "Organization" in old:
        return None
    script = '''
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "TODO: Brand Name",
  "url": "https://example.com",
  "logo": "https://example.com/logo.png"
}
</script>
'''
    new = _inject_in_head(old, script)
    if new == old:
        return None
    return {
        "finding_id": finding.id,
        "commit_scope": "structured-data",
        "files": {path: new},
        "diff": make_unified_diff(path, old, new),
        "rationale": f"Resolves {finding.id}: injected Organization JSON-LD.",
    }


def _fix_broken_links(finding: Finding, repo_path: Path) -> dict[str, Any] | None:
    # Without a mapping from broken URL → replacement, comment-flag for review.
    path = finding.mapped_file
    if not path:
        return None
    full = repo_path / path
    if not full.exists():
        return None
    old = full.read_text(encoding="utf-8")
    note = f"\n<!-- SEO-AGENT: review broken internal links related to {finding.id}: {finding.evidence[:200]} -->\n"
    new = old + note
    return {
        "finding_id": finding.id,
        "commit_scope": "internal-links",
        "files": {path: new},
        "diff": make_unified_diff(path, old, new),
        "rationale": f"Resolves {finding.id}: flagged broken internal links for manual URL update.",
    }


def _inject_in_head(html: str, snippet: str) -> str:
    import re
    if re.search(r"</head>", html, re.I):
        return re.sub(r"</head>", snippet + "</head>", html, count=1, flags=re.I)
    # JSX / TSX metadata-style files: prepend a comment block for the human reviewer
    return snippet + html
