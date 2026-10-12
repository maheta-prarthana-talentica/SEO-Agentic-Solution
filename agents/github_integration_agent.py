"""GitHub Integration Agent (Phase 4 / Section 6).

Creates branch seo-agent/<run_id>, commits per fix category (Conventional Commits),
opens a PR with the Appendix 15.2 template. Never merges.

Branch is created ONLY when there is at least one file to commit — otherwise we
would leave empty orphan branches (previous bug).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.models import Finding, FindingStatus
from tools.github_client import GitHubClient
from tools.logging_utils import TraceLogger


def run(
    *,
    repo_url: str,
    run_id: str,
    diffs: list[dict[str, Any]],
    findings: list[Finding],
    github_token: str | None = None,
    trace: TraceLogger | None = None,
) -> dict[str, Any]:
    normalized = _normalize_repo(repo_url)
    client = GitHubClient(token=github_token, repo=normalized)

    if not client.enabled:
        if trace:
            trace.log("GitHubIntegrationAgent", "skipped_no_token", level="warning")
        return {
            "branch_name": None,
            "pr_url": None,
            "error": "GITHUB_TOKEN/repo not configured",
            "status": "failed",
            "message": "GitHub token or repository was not configured for Phase 2.",
        }

    auth_err = client.probe_access()
    if auth_err:
        if trace:
            trace.log("GitHubIntegrationAgent", "auth_failed",
                      {"error": auth_err}, level="error")
        return {
            "branch_name": None,
            "pr_url": None,
            "error": auth_err,
            "status": "failed",
            "message": auth_err,
        }

    # Group verified, non-blocked diffs that actually contain file contents
    by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped_empty = 0
    for d in diffs:
        if d.get("blocked") or not d.get("verified", True):
            continue
        if not d.get("files"):
            skipped_empty += 1
            continue
        scope = d.get("commit_scope") or "seo-fix"
        by_scope[scope].append(d)

    if not by_scope:
        msg = (
            "No file patches were generated to commit "
            f"(proposals={len(diffs)}, empty_file_payloads={skipped_empty}). "
            "Phase 2 mapped findings but could not produce code changes for this stack."
        )
        if trace:
            trace.log("GitHubIntegrationAgent", "no_files_to_commit",
                      {"diffs": len(diffs), "skipped_empty": skipped_empty}, level="warning")
        return {
            "branch_name": None,
            "pr_url": None,
            "error": msg,
            "status": "failed",
            "message": msg,
        }

    branch = f"seo-agent/{run_id}"
    try:
        client.create_branch(branch)
    except Exception as exc:  # noqa: BLE001
        if trace:
            trace.log("GitHubIntegrationAgent", "branch_failed",
                      {"error": str(exc)}, level="error")
        return {
            "branch_name": None,
            "pr_url": None,
            "error": str(exc),
            "status": "failed",
            "message": f"Could not create branch: {exc}",
        }

    commit_shas: list[str] = []
    finding_table_rows: list[str] = []
    findings_by_id = {f.id: f for f in findings}
    commit_errors: list[str] = []

    for scope, group in by_scope.items():
        files: dict[str, str] = {}
        finding_ids = []
        for item in group:
            files.update(item.get("files") or {})
            finding_ids.append(item.get("finding_id"))
        message = f"fix(seo): {scope} ({', '.join(fid for fid in finding_ids if fid)})"
        try:
            sha = client.commit_files(branch, files, message)
            if sha:
                commit_shas.append(sha)
            if trace:
                trace.log("GitHubIntegrationAgent", "committed",
                          {"scope": scope, "files": list(files.keys()), "sha": sha})
            for fid in finding_ids:
                f = findings_by_id.get(fid)
                if f:
                    f.status = FindingStatus.PR_OPENED
                for path in files:
                    finding_table_rows.append(
                        f"| {fid} | `{path}` | see diff | applied |"
                    )
        except Exception as exc:  # noqa: BLE001
            commit_errors.append(f"{scope}: {exc}")
            if trace:
                trace.log("GitHubIntegrationAgent", "commit_failed",
                          {"scope": scope, "error": str(exc)}, level="error")

    if not commit_shas:
        msg = "Branch created but all commits failed: " + "; ".join(commit_errors or ["unknown"])
        return {
            "branch_name": branch,
            "pr_url": None,
            "error": msg,
            "status": "failed",
            "message": msg,
        }

    body = _pr_body(run_id, findings, finding_table_rows, by_scope)
    title = f"seo-agent: automated SEO fixes for run {run_id}"
    result = client.open_pr(branch, title, body)

    if result.pr_number and trace:
        try:
            ci = client.get_pr_ci_status(result.pr_number)
            trace.log("GitHubIntegrationAgent", "ci_status", ci)
        except Exception as exc:  # noqa: BLE001
            trace.log("GitHubIntegrationAgent", "ci_status_error",
                      {"error": str(exc)}, level="warning")

    if trace:
        trace.log("GitHubIntegrationAgent", "pr_opened",
                  {"pr_url": result.pr_url, "error": result.error})

    if result.pr_url:
        return {
            "branch_name": branch,
            "pr_url": result.pr_url,
            "pr_number": result.pr_number,
            "commits": commit_shas,
            "error": None,
            "status": "success",
            "message": f"Pull request opened: {result.pr_url}",
        }

    err = result.error or "GitHub accepted the branch/commits but did not return a PR URL."
    return {
        "branch_name": branch,
        "pr_url": None,
        "pr_number": result.pr_number,
        "commits": commit_shas,
        "error": err,
        "status": "failed",
        "message": f"Commits pushed to `{branch}` but PR creation failed: {err}",
    }


def _normalize_repo(repo_url: str) -> str:
    import re
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", repo_url)
    if m:
        return f"{m.group('owner')}/{m.group('name')}"
    return repo_url.removesuffix(".git")


def _pr_body(
    run_id: str,
    findings: list[Finding],
    rows: list[str],
    by_scope: dict[str, list],
) -> str:
    """Appendix 15.2 PR description template."""
    addressed = [f for f in findings if f.status == FindingStatus.PR_OPENED]
    lines = [
        "## Summary of SEO findings addressed in this PR",
        "",
        f"Automated remediation run `{run_id}` grouped commits by fix category: "
        + ", ".join(f"`{s}` ({len(g)})" for s, g in by_scope.items()) + ".",
        "",
        "| Finding ID | File changed | Before | After |",
        "|---|---|---|---|",
    ]
    lines.extend(rows or ["| — | — | — | — |"])
    lines += [
        "",
        "## Expected SEO impact",
        "",
    ]
    for f in addressed:
        lines.append(f"- **{f.id} {f.title}**: {f.recommendation}")
    lines += [
        "",
        "## Reviewer checklist",
        "",
        "- [ ] Build / CI passed",
        "- [ ] Visually verified affected pages",
        "- [ ] No denylisted files touched",
        "- [ ] Commit messages reference finding IDs",
        "",
        "_This PR was opened by seo-agent-bot. Merge is intentionally manual — the agent never auto-merges._",
    ]
    return "\n".join(lines)
