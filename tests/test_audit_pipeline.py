"""Unit tests for Phase 1 audit agents against the offline fixture site."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_fixture_audit_produces_findings_and_report():
    from agents.orchestrator import run_audit

    run, md = run_audit(use_fixture=True)
    assert run.overall_score >= 0
    assert run.overall_score <= 100
    assert len(run.findings) > 0
    assert "SUMMARY" in md
    assert "DETAILED FINDINGS" in md
    assert "PRIORITIZATION" in md
    assert "TOP RECOMMENDATIONS" in md
    assert "PHASE 2 READINESS" in md
    assert "Do you want to proceed to Phase 2" in md
    assert (ROOT / "reports" / f"{run.run_id}.md").exists()


def test_denylist_blocks_env_files():
    from tools.diff_utils import enforce_denylist, is_denied

    assert is_denied(".env")
    assert is_denied("src/auth/login.ts")
    assert not is_denied("app/layout.tsx")
    denied = enforce_denylist([".env", "app/page.tsx", "package-lock.json"])
    assert ".env" in denied
    assert "package-lock.json" in denied
    assert "app/page.tsx" not in denied


def test_schema_validator_flags_incomplete_article():
    from tools.schema_validator import validate_json_ld_blocks

    raw = ['{"@context":"https://schema.org","@type":"Article","headline":"Hi"}']
    result = validate_json_ld_blocks("https://example.com/a", raw)
    assert "Article" in result.types_present
    assert any(t == "Article" for t, _ in result.missing_required_props)


def test_prioritization_quick_win():
    from backend.models import Category, Finding, FixType, Severity
    from agents.prioritization import group_by_quadrant

    f = Finding(
        category=Category.ON_PAGE, severity=Severity.HIGH,
        title="Missing title", description="x", evidence="y", recommendation="z",
        fix_type=FixType.AUTO_FIXABLE, impact_score=5, effort_score=1,
    )
    groups = group_by_quadrant([f])
    assert f in groups["quick_win"]
