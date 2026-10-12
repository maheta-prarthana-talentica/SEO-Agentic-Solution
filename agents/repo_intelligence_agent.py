"""Repo Intelligence Agent (Phase 2 / Section 5.1).

Clones/indexes the target GitHub repo, detects framework + conventions, and maps
each finding to candidate source files (FR-3.1 – FR-3.4).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from backend.models import Finding, FindingStatus, FixType
from tools.logging_utils import TraceLogger
from tools.repo_scanner import index_repo, map_finding_to_files

CACHE_DIR = Path(__file__).resolve().parent.parent / "repo_cache"


def run(
    repo_url_or_name: str,
    findings: list[Finding],
    *,
    local_path: str | Path | None = None,
    trace: TraceLogger | None = None,
) -> dict[str, Any]:
    """Returns {repo_path, framework, conventions, index, findings (with mapped_file)}.

    If GITHUB_TOKEN is unset and no local_path is given, returns findings unchanged
    with framework='unavailable' (graceful skip).
    """
    repo_path = Path(local_path) if local_path else _resolve_repo(repo_url_or_name, trace)
    if repo_path is None or not repo_path.exists():
        if trace:
            trace.log("RepoIntelligenceAgent", "repo_unavailable",
                      {"repo": repo_url_or_name}, level="warning")
        return {
            "repo_path": None,
            "framework": "unavailable",
            "conventions": {},
            "index": None,
            "findings": findings,
        }

    idx = index_repo(repo_path)
    if trace:
        trace.log("RepoIntelligenceAgent", "indexed", {
            "framework": idx.framework,
            "files": len(idx.files),
            "meta_helper": idx.conventions.get("meta_helper"),
        })

    if idx.framework == "unsupported":
        if trace:
            trace.log("RepoIntelligenceAgent", "unsupported_stack",
                      {"path": str(repo_path)}, level="warning")
        # Still attempt mapping with heuristics; surface a note via conventions
        idx.conventions["warning"] = (
            "Unsupported stack detected. Mapping uses path heuristics only; "
            "prefer Next.js for full automation support (FR-3.4)."
        )

    mapped: list[Finding] = []
    for f in findings:
        candidates = map_finding_to_files(f.title, f.fix_category, idx)
        if candidates:
            f.mapped_file = candidates[0]
            f.status = FindingStatus.MAPPED
            if trace:
                trace.log("RepoIntelligenceAgent", "mapped_finding",
                          {"candidates": candidates[:3]}, finding_id=f.id)
        mapped.append(f)

    # Soft accuracy note for reporting: count mapped / mapable auto-fixables
    auto = [f for f in mapped if f.fix_type == FixType.AUTO_FIXABLE]
    mapped_auto = [f for f in auto if f.mapped_file]
    if trace and auto:
        pct = round(100 * len(mapped_auto) / len(auto))
        trace.log("RepoIntelligenceAgent", "mapping_coverage",
                  {"auto_fixable": len(auto), "mapped": len(mapped_auto), "pct": pct})

    return {
        "repo_path": repo_path,
        "framework": idx.framework,
        "conventions": idx.conventions,
        "index": {
            "files": idx.files,
            "file_signals": idx.file_signals,
        },
        "findings": mapped,
    }


def _resolve_repo(repo_url_or_name: str, trace: TraceLogger | None) -> Path | None:
    """Clone (or reuse cache) of owner/name or https GitHub URL into repo_cache/."""
    CACHE_DIR.mkdir(exist_ok=True)
    slug = _slug(repo_url_or_name)
    dest = CACHE_DIR / slug

    if dest.exists() and any(dest.iterdir()):
        if trace:
            trace.log("RepoIntelligenceAgent", "using_cached_clone", {"path": str(dest)})
        return dest

    token = os.getenv("GITHUB_TOKEN")
    clone_url = _to_clone_url(repo_url_or_name, token)
    try:
        import git  # GitPython
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        git.Repo.clone_from(clone_url, str(dest), depth=1)
        if trace:
            trace.log("RepoIntelligenceAgent", "cloned", {"path": str(dest)})
        return dest
    except Exception as exc:  # noqa: BLE001
        if trace:
            trace.log("RepoIntelligenceAgent", "clone_failed",
                      {"error": str(exc)}, level="error")
        # Last resort: treat the string as a local path
        local = Path(repo_url_or_name)
        return local if local.exists() else None


def _slug(repo: str) -> str:
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", repo)
    if m:
        return f"{m.group('owner')}__{m.group('name')}"
    return re.sub(r"[^\w.-]+", "_", repo.replace("/", "__"))


def _to_clone_url(repo: str, token: str | None) -> str:
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", repo)
    if m:
        owner, name = m.group("owner"), m.group("name")
    elif "/" in repo and not repo.startswith("http"):
        owner, name = repo.split("/", 1)
        name = name.removesuffix(".git")
    else:
        return repo
    if token:
        # Fine-grained PATs work with x-access-token; classic ghp_ tokens do too.
        from urllib.parse import quote
        safe = quote(token, safe="")
        return f"https://x-access-token:{safe}@github.com/{owner}/{name}.git"
    return f"https://github.com/{owner}/{name}.git"
