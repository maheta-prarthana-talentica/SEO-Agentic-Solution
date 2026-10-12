"""Minimal self-check that does not require pytest or network.

Run:  python scripts/smoke_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from tools.diff_utils import is_denied
    from tools.schema_validator import validate_json_ld_blocks
    from agents.orchestrator import run_audit

    assert is_denied(".env"), "denylist should block .env"
    assert not is_denied("app/layout.tsx")

    result = validate_json_ld_blocks(
        "https://example.com",
        ['{"@context":"https://schema.org","@type":"Organization","name":"Acme","url":"https://example.com","logo":"https://example.com/l.png"}'],
    )
    assert "Organization" in result.types_present

    print("Running fixture audit...")
    run, md = run_audit(use_fixture=True)
    assert "SUMMARY" in md and "PHASE 2 READINESS" in md
    assert len(run.findings) > 0
    print(f"OK — score={run.overall_score}/100 findings={len(run.findings)} run_id={run.run_id}")
    print(md[:1200])
    print("\n...")
    print(md[-400:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
