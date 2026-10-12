"""Shared LangGraph state schema for the Orchestrator graph (Section 5.2 high-level flow).

Every node in `agents/orchestrator.py` reads/writes this TypedDict. Keeping it as a plain
TypedDict (rather than spreading state across globals) is what lets the orchestrator
retry individual nodes with backoff without corrupting sibling agents' output
(Reliability NFR), and lets `tools/logging_utils.py` snapshot the whole run for the
trace viewer.
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from backend.models import AuditRun


class RunConfig(TypedDict):
    target_url: str
    repo_url: Optional[str]
    github_token: Optional[str]
    github_token_configured: bool
    page_limit: int
    use_fixture: bool  # True => crawl tests/fixtures/sample_site instead of the network


class PipelineState(TypedDict, total=False):
    """`total=False`: nodes only need to set the keys they own; the orchestrator merges
    keys across nodes (see agents/orchestrator.py::merge_findings)."""

    config: RunConfig
    run: AuditRun

    # Phase 1 outputs (parallel audit agents; Section 5.2 step 2)
    crawl_pages: list[Any]  # list[tools.crawler.PageRecord]
    technical_findings: list[Any]
    onpage_findings: list[Any]
    content_findings: list[Any]
    structured_data_findings: list[Any]
    performance_findings: list[Any]

    # Phase 2 outputs (repo intelligence; Section 5.2 step 4)
    repo_index: Optional[dict]
    repo_conventions: Optional[dict]
    framework: Optional[str]

    # Phase 3 outputs (remediation + verification; Section 5.2 steps 5-6)
    proposed_diffs: list[dict]
    verification_results: list[dict]

    # Phase 4 outputs (GitHub; Section 5.2 step 7)
    branch_name: Optional[str]
    pr_url: Optional[str]

    # Final report (Section 5.2 step 8)
    report_markdown: Optional[str]

    errors: list[str]
