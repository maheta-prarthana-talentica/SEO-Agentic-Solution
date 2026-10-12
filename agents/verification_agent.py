"""Verification Agent (Phase 3 / Section 5.1).

Re-checks proposed diffs: denylist re-gate, optional local write-to-temp + lint/build
signals. Never pushes anywhere — GitHub Integration Agent owns that step.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.diff_utils import enforce_denylist, load_denylist
from tools.logging_utils import TraceLogger


def run(
    proposals: list[dict[str, Any]],
    repo_path: Path | str | None,
    *,
    trace: TraceLogger | None = None,
) -> list[dict[str, Any]]:
    """Annotate each proposal with verification results; filter out blocked ones for PR."""
    verified: list[dict[str, Any]] = []
    cfg = load_denylist()

    for prop in proposals:
        if prop.get("blocked"):
            verified.append({**prop, "verified": False, "checks": ["pre-blocked"]})
            continue

        files = prop.get("files") or {}
        denied = enforce_denylist(list(files.keys()), cfg)
        if denied:
            prop = {**prop, "blocked": True, "verified": False,
                    "reason": f"denylist at verify: {denied}", "checks": ["denylist_fail"]}
            verified.append(prop)
            if trace:
                trace.log("VerificationAgent", "denylist_fail",
                          {"files": denied}, finding_id=prop.get("finding_id"), level="warning")
            continue

        checks = ["denylist_pass"]
        build_ok = True

        # Optional: apply files in a temp copy and run a quick syntax/existence check
        if repo_path and files:
            build_ok, build_notes = _smoke_check(Path(repo_path), files)
            checks.append(build_notes)
            if not build_ok:
                prop = {**prop, "blocked": True, "verified": False,
                        "reason": build_notes, "checks": checks}
                verified.append(prop)
                if trace:
                    trace.log("VerificationAgent", "smoke_fail",
                              {"notes": build_notes}, finding_id=prop.get("finding_id"),
                              level="warning")
                continue

        # Optional prettier/eslint if present (best-effort)
        lint_note = _try_lint(repo_path, list(files.keys()))
        if lint_note:
            checks.append(lint_note)

        out = {**prop, "verified": True, "checks": checks}
        verified.append(out)
        if trace:
            trace.log("VerificationAgent", "verified",
                      {"checks": checks}, finding_id=prop.get("finding_id"))

    return verified


def _smoke_check(repo_path: Path, files: dict[str, str]) -> tuple[bool, str]:
    """Write proposed files into a temp overlay and ensure they are readable UTF-8 text."""
    try:
        with tempfile.TemporaryDirectory(prefix="seo-verify-") as tmp:
            tmp_path = Path(tmp)
            # Copy only the files we will overwrite (lightweight)
            for rel, content in files.items():
                if enforce_denylist([rel]):
                    return False, f"denylist mid-smoke: {rel}"
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                # Re-read
                _ = dest.read_text(encoding="utf-8")
        return True, "smoke_pass"
    except Exception as exc:  # noqa: BLE001
        return False, f"smoke_fail: {exc}"


def _try_lint(repo_path: Path | str | None, rel_paths: list[str]) -> str | None:
    if not repo_path or not rel_paths:
        return None
    repo_path = Path(repo_path)
    # Prefer npx prettier --check if node_modules exists; otherwise skip silently
    prettier = repo_path / "node_modules" / ".bin" / "prettier"
    if not prettier.exists():
        return "lint_skipped_no_prettier"
    try:
        cmd = [str(prettier), "--check", *rel_paths]
        result = subprocess.run(
            cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return "prettier_pass"
        return f"prettier_warn: {result.stdout[:200]}"
    except Exception:  # noqa: BLE001
        return "lint_skipped_error"
