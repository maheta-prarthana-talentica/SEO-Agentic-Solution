"""Diff utilities + hard denylist enforcement (Section 6.4).

`enforce_denylist` is a hard gate in code — not a prompt instruction — so prompt
injection via crawled content cannot expand file-access scope.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DENYLIST_PATH = Path(__file__).resolve().parent.parent / "config" / "denylist.yaml"


@dataclass
class DenylistConfig:
    paths: list[str]
    extensions_never_touched: list[str]
    max_diff_lines_per_commit: int
    max_files_per_commit: int


def load_denylist() -> DenylistConfig:
    with _DENYLIST_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return DenylistConfig(
        paths=list(data.get("paths") or []),
        extensions_never_touched=list(data.get("extensions_never_touched") or []),
        max_diff_lines_per_commit=int(data.get("max_diff_lines_per_commit") or 400),
        max_files_per_commit=int(data.get("max_files_per_commit") or 15),
    )


def is_denied(repo_relative_path: str, cfg: DenylistConfig | None = None) -> bool:
    cfg = cfg or load_denylist()
    path = repo_relative_path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    suffix = Path(path).suffix.lower()
    denied_exts = {
        e.lower() if e.startswith(".") else f".{e.lower()}"
        for e in cfg.extensions_never_touched
    }
    if suffix in denied_exts:
        return True
    for pattern in cfg.paths:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern):
            return True
    return False


def enforce_denylist(file_paths: list[str], cfg: DenylistConfig | None = None) -> list[str]:
    """Returns the subset of paths that are DENIED (so callers can fail closed)."""
    cfg = cfg or load_denylist()
    return [p for p in file_paths if is_denied(p, cfg)]


def count_diff_lines(diff_text: str) -> int:
    return sum(1 for line in diff_text.splitlines()
               if line.startswith("+") or line.startswith("-"))


def diff_within_cap(diff_text: str, file_count: int, cfg: DenylistConfig | None = None) -> bool:
    cfg = cfg or load_denylist()
    if file_count > cfg.max_files_per_commit:
        return False
    return count_diff_lines(diff_text) <= cfg.max_diff_lines_per_commit


def make_unified_diff(path: str, old: str, new: str) -> str:
    """Minimal unified-diff generator (no difflib dependency surprises)."""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    if not old_lines and not old.endswith("\n") and old:
        old_lines = [old]
    return "".join(difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
    ))


def apply_unified_diff_preview(path: str, old: str, new: str) -> dict[str, Any]:
    return {"path": path, "diff": make_unified_diff(path, old, new), "new_content": new}
