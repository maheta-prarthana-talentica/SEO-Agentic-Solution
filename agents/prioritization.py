"""Prioritization helpers (FR-2.2, FR-2.3, FR-2.4).

Deduplicates findings that share a common root cause and ranks them by the
impact × effort scoring model used in Section 5.2.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from backend.models import Finding, FixType

_FIX_CAT_PATH = Path(__file__).resolve().parent.parent / "config" / "fix_categories.yaml"


def load_fix_categories() -> dict[str, Any]:
    if not _FIX_CAT_PATH.exists():
        return {}
    with _FIX_CAT_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("fix_categories", {})


def apply_fix_category_tags(findings: list[Finding]) -> list[Finding]:
    """Align Finding.fix_type with config/fix_categories.yaml when a fix_category is set."""
    cats = load_fix_categories()
    level_map = {
        "auto-fix": FixType.AUTO_FIXABLE,
        "assisted": FixType.ASSISTED,
        "manual": FixType.MANUAL,
    }
    for f in findings:
        if f.fix_category and f.fix_category in cats:
            level = cats[f.fix_category].get("automation_level", "manual")
            f.fix_type = level_map.get(level, FixType.MANUAL)
    return findings


def deduplicate_by_root_cause(findings: list[Finding]) -> list[Finding]:
    """FR-2.3: keep one finding per root_cause_key, merging affected_pages."""
    keep: list[Finding] = []
    by_key: dict[str, Finding] = {}
    for f in findings:
        if not f.root_cause_key:
            keep.append(f)
            continue
        if f.root_cause_key not in by_key:
            by_key[f.root_cause_key] = f
            keep.append(f)
        else:
            existing = by_key[f.root_cause_key]
            merged = list(dict.fromkeys(existing.affected_pages + f.affected_pages))
            existing.affected_pages = merged
            if f.severity.weight > existing.severity.weight:
                existing.severity = f.severity
    return keep


def rank_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-f.priority_score, -f.severity.weight, f.effort_score))


def group_by_quadrant(findings: list[Finding]) -> dict[str, list[Finding]]:
    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.quadrant()].append(f)
    return dict(groups)


def compute_category_scores(findings: list[Finding]) -> dict[str, int]:
    """Simple deduction model: start at 100, deduct by severity/count capped at 0."""
    from backend.models import Category, CategoryScore, Severity

    deductions = {Severity.CRITICAL: 15, Severity.HIGH: 10, Severity.MEDIUM: 5, Severity.LOW: 2}
    scores: dict[str, int] = {c.value: 100 for c in Category}
    counts: dict[str, int] = {c.value: 0 for c in Category}
    for f in findings:
        scores[f.category.value] = max(0, scores[f.category.value] - deductions[f.severity])
        counts[f.category.value] += 1
    return scores


def compute_overall_score(category_scores: dict[str, int]) -> int:
    if not category_scores:
        return 100
    return round(sum(category_scores.values()) / len(category_scores))
