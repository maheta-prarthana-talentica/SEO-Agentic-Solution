"""Audit run endpoints — Phase 1 (URL audit) and optional Phase 2 (GitHub remediation)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from agents.orchestrator import run_audit
from agents.prioritization import group_by_quadrant
from backend.models import AuditRun, Finding, FixType

router = APIRouter(tags=["audit"])

_RUNS: dict[str, dict] = {}


class AuditRequest(BaseModel):
    """Phase 1 requires a website URL. Phase 2 fields are optional."""

    url: HttpUrl = Field(..., description="Website URL to crawl and audit (Phase 1)")
    page_limit: Optional[int] = Field(50, ge=1, le=200)
    use_fixture: bool = False

    # Phase 2+ (optional — only when user opts in)
    enable_phase2: bool = Field(
        False,
        description="If true, run repo intelligence + remediation + GitHub PR",
    )
    # Backward-compatible alias
    enable_remediation: bool = False
    github_repo_url: Optional[str] = Field(
        None,
        description="GitHub repo as https://github.com/owner/name or owner/name",
    )
    repo_url: Optional[str] = None  # alias for github_repo_url
    github_token: Optional[str] = Field(
        None,
        description="Fine-grained PAT for this run only (not persisted). "
        "Scopes: contents + pull requests + metadata.",
    )


class FindingBrief(BaseModel):
    id: str
    title: str
    severity: str
    category: str
    fix_type: str
    recommendation: str
    priority_score: float = 0


class StructuredReport(BaseModel):
    overall_score: int
    key_strengths: list[str]
    key_weaknesses: list[str]
    quick_wins: list[FindingBrief]
    high_impact_high_effort: list[FindingBrief]
    low_impact: list[FindingBrief]
    top_recommendations: list[FindingBrief]
    phase2_auto_fixable: list[FindingBrief]
    phase2_assisted: list[FindingBrief]
    phase2_manual: list[FindingBrief]
    phase2_cta: str = "Do you want to proceed to Phase 2 (GitHub-based code fixes)?"


class AuditResponse(BaseModel):
    run_id: str
    overall_score: int
    findings_count: int
    report_markdown: str
    structured_report: StructuredReport
    run: AuditRun
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    phase2_status: str = "not_run"
    phase2_message: Optional[str] = None


class Phase2Request(BaseModel):
    github_repo_url: str = Field(..., description="owner/name or full GitHub URL")
    github_token: str = Field(..., min_length=8, description="GitHub PAT for this run")
    page_limit: Optional[int] = 50


@contextmanager
def _temporary_github_creds(token: str | None, repo: str | None):
    """Apply request-scoped GitHub credentials without permanently mutating the process env."""
    from tools.github_client import normalize_github_token

    prev_token = os.environ.get("GITHUB_TOKEN")
    prev_repo = os.environ.get("GITHUB_REPO")
    try:
        cleaned = normalize_github_token(token)
        if cleaned:
            os.environ["GITHUB_TOKEN"] = cleaned
        if repo:
            # Normalize to owner/name for env consumers
            os.environ["GITHUB_REPO"] = _normalize_repo(repo)
        yield
    finally:
        if prev_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = prev_token
        if prev_repo is None:
            os.environ.pop("GITHUB_REPO", None)
        else:
            os.environ["GITHUB_REPO"] = prev_repo


def _normalize_repo(repo: str) -> str:
    import re

    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", repo)
    if m:
        return f"{m.group('owner')}/{m.group('name')}"
    return repo.removesuffix(".git").strip("/")


def _finding_brief(f: Finding) -> FindingBrief:
    return FindingBrief(
        id=f.id,
        title=f.title,
        severity=f.severity.display,
        category=f.category.value,
        fix_type=f.fix_type.value,
        recommendation=f.recommendation,
        priority_score=f.priority_score,
    )


def build_structured_report(run: AuditRun) -> StructuredReport:
    findings = run.findings
    groups = group_by_quadrant(findings)

    strengths = [
        f"{cs.category.value}: {cs.score}/100"
        for cs in run.category_scores
        if cs.score >= 80
    ] or ["Crawl completed and produced evidence-backed findings."]

    weaknesses = [
        f.title for f in findings if f.severity.value in ("critical", "high")
    ][:5] or [f.title for f in findings[:3]] or ["No major weaknesses detected."]

    auto = [f for f in findings if f.fix_type == FixType.AUTO_FIXABLE]
    assisted = [f for f in findings if f.fix_type == FixType.ASSISTED]
    manual = [f for f in findings if f.fix_type == FixType.MANUAL]

    return StructuredReport(
        overall_score=run.overall_score,
        key_strengths=strengths,
        key_weaknesses=weaknesses,
        quick_wins=[_finding_brief(f) for f in groups.get("quick_win", [])],
        high_impact_high_effort=[
            _finding_brief(f) for f in groups.get("high_impact_high_effort", [])
        ],
        low_impact=[_finding_brief(f) for f in groups.get("low_impact", [])],
        top_recommendations=[_finding_brief(f) for f in findings[:10]],
        phase2_auto_fixable=[_finding_brief(f) for f in auto],
        phase2_assisted=[_finding_brief(f) for f in assisted],
        phase2_manual=[_finding_brief(f) for f in manual],
    )


def _store_and_respond(run: AuditRun, md: str, pr_url: str | None = None) -> AuditResponse:
    structured = build_structured_report(run)
    pr = pr_url or getattr(run, "pr_url", None)
    _RUNS[run.run_id] = {
        "run": run,
        "markdown": md,
        "pr_url": pr,
        "branch_name": getattr(run, "branch_name", None),
        "phase2_status": getattr(run, "phase2_status", "not_run"),
        "phase2_message": getattr(run, "phase2_message", None),
    }
    return AuditResponse(
        run_id=run.run_id,
        overall_score=run.overall_score,
        findings_count=len(run.findings),
        report_markdown=md,
        structured_report=structured,
        run=run,
        pr_url=pr,
        branch_name=getattr(run, "branch_name", None),
        phase2_status=getattr(run, "phase2_status", "not_run") or "not_run",
        phase2_message=getattr(run, "phase2_message", None),
    )


@router.post("/audit", response_model=AuditResponse)
def create_audit(req: AuditRequest):
    """Phase 1 audit (website URL). Optionally enable Phase 2 with GitHub creds."""
    enable_p2 = req.enable_phase2 or req.enable_remediation
    repo = req.github_repo_url or req.repo_url

    if enable_p2:
        if not repo:
            raise HTTPException(
                status_code=400,
                detail="Phase 2 requires github_repo_url (e.g. owner/name or https://github.com/owner/name).",
            )
        if not (req.github_token or os.getenv("GITHUB_TOKEN")):
            raise HTTPException(
                status_code=400,
                detail="Phase 2 requires github_token (or GITHUB_TOKEN in server .env).",
            )

    try:
        with _temporary_github_creds(req.github_token, repo):
            run, md = run_audit(
                target_url=str(req.url),
                repo_url=repo,
                github_token=req.github_token,
                page_limit=req.page_limit,
                use_fixture=req.use_fixture,
                enable_remediation=enable_p2,
            )
        pr_url = getattr(run, "pr_url", None)
        return _store_and_respond(run, md, pr_url)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/audit/{run_id}/phase2", response_model=AuditResponse)
def run_phase2(run_id: str, req: Phase2Request):
    """Run Phase 2+ remediation for an existing Phase 1 audit (same target URL)."""
    entry = _RUNS.get(run_id)
    if not entry:
        from pathlib import Path

        reports = Path(__file__).resolve().parents[2] / "reports"
        json_path = reports / f"{run_id}.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="Run not found. Run Phase 1 first.")
        prior = AuditRun.model_validate_json(json_path.read_text(encoding="utf-8"))
    else:
        prior = entry["run"]

    try:
        with _temporary_github_creds(req.github_token, req.github_repo_url):
            run, md = run_audit(
                target_url=prior.target_url,
                repo_url=req.github_repo_url,
                github_token=req.github_token,
                page_limit=req.page_limit or prior.page_limit,
                use_fixture=False,
                enable_remediation=True,
            )
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _store_and_respond(run, md, getattr(run, "pr_url", None))


@router.get("/audit/{run_id}", response_model=AuditResponse)
def get_audit(run_id: str):
    entry = _RUNS.get(run_id)
    if not entry:
        from pathlib import Path

        reports = Path(__file__).resolve().parents[2] / "reports"
        json_path = reports / f"{run_id}.json"
        md_path = reports / f"{run_id}.md"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="Run not found")
        run = AuditRun.model_validate_json(json_path.read_text(encoding="utf-8"))
        md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        return _store_and_respond(run, md, getattr(run, "pr_url", None))

    run = entry["run"]
    return AuditResponse(
        run_id=run.run_id,
        overall_score=run.overall_score,
        findings_count=len(run.findings),
        report_markdown=entry["markdown"],
        structured_report=build_structured_report(run),
        run=run,
        pr_url=entry.get("pr_url") or getattr(run, "pr_url", None),
        branch_name=entry.get("branch_name") or getattr(run, "branch_name", None),
        phase2_status=entry.get("phase2_status")
        or getattr(run, "phase2_status", None)
        or "not_run",
        phase2_message=entry.get("phase2_message") or getattr(run, "phase2_message", None),
    )


@router.get("/audits")
def list_audits():
    from pathlib import Path

    reports = Path(__file__).resolve().parents[2] / "reports"
    items: list[dict[str, Any]] = []
    if reports.exists():
        for p in sorted(reports.glob("*.json"), reverse=True):
            try:
                run = AuditRun.model_validate_json(p.read_text(encoding="utf-8"))
                items.append({
                    "run_id": run.run_id,
                    "target_url": run.target_url,
                    "overall_score": run.overall_score,
                    "findings_count": len(run.findings),
                    "completed_at": run.completed_at,
                })
            except Exception:  # noqa: BLE001
                continue
    for run_id, entry in _RUNS.items():
        if not any(i["run_id"] == run_id for i in items):
            run = entry["run"]
            items.append({
                "run_id": run.run_id,
                "target_url": run.target_url,
                "overall_score": run.overall_score,
                "findings_count": len(run.findings),
                "completed_at": run.completed_at,
            })
    return items
