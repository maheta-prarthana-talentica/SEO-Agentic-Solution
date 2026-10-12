"""CLI entry point for a one-off SEO audit (Phase 1 demos + optional remediation)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/run_demo_audit.py` from repo root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agents.orchestrator import run_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SEO Agentic Solutions — run an audit")
    parser.add_argument("--url", default="https://example.com",
                        help="Website URL to audit (ignored when --fixture is set)")
    parser.add_argument("--fixture", action="store_true",
                        help="Audit the offline sample site under tests/fixtures/sample_site")
    parser.add_argument("--repo", default=None,
                        help="GitHub repo (owner/name) for Phase 2+ remediation")
    parser.add_argument("--remediate", action="store_true",
                        help="Enable Phase 2-4 repo mapping + code fixes + PR (requires GITHUB_TOKEN)")
    parser.add_argument("--pages", type=int, default=None, help="Max pages to crawl")
    args = parser.parse_args()

    print(f"Running SEO audit ({'fixture' if args.fixture else args.url})...")
    run, md = run_audit(
        target_url=args.url,
        repo_url=args.repo,
        page_limit=args.pages,
        use_fixture=args.fixture,
        enable_remediation=args.remediate,
    )
    print(md)
    print(f"\n[Wrote reports/{run.run_id}.md and reports/{run.run_id}.json]")
    print(f"Overall SEO score: {run.overall_score}/100 | Findings: {len(run.findings)}")
    if run.errors:
        print("Errors:", *run.errors, sep="\n  - ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
