"""Shared data models for the SEO Agentic Solutions pipeline.

The `Finding` shape follows Appendix 15.1 of the requirements doc:
    id, category, severity (critical/high/medium/low), url, evidence, recommendation,
    autoFixable, mappedFile, status

Every agent produces/consumes `Finding` objects; this is the contract between agents
referenced throughout `agents/orchestrator.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    TECHNICAL = "technical"
    ON_PAGE = "on-page"
    CONTENT = "content"
    STRUCTURED_DATA = "structured-data"
    PERFORMANCE = "performance"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def display(self) -> str:
        """Maps the internal 4-tier scale to the report's High/Medium/Low presentation."""
        return {"critical": "High", "high": "High", "medium": "Medium", "low": "Low"}[self.value]

    @property
    def weight(self) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}[self.value]


class FixType(str, Enum):
    AUTO_FIXABLE = "auto-fixable"
    ASSISTED = "assisted"
    MANUAL = "manual"


class FindingStatus(str, Enum):
    OPEN = "open"
    MAPPED = "mapped"
    FIX_GENERATED = "fix-generated"
    BLOCKED_BY_DENYLIST = "blocked-by-denylist"
    VERIFIED = "verified"
    PR_OPENED = "pr-opened"
    RESOLVED = "resolved"
    WONTFIX = "wontfix"


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: _short_id("F"))
    category: Category
    severity: Severity
    title: str
    description: str
    evidence: str
    recommendation: str
    fix_type: FixType
    affected_pages: list[str] = Field(default_factory=list)  # ["Site-wide"] or list of URLs
    root_cause_key: Optional[str] = None  # groups findings that share one template/cause (FR-2.3)
    impact_score: int = Field(ge=1, le=5, default=3)  # 1=low impact, 5=critical impact
    effort_score: int = Field(ge=1, le=5, default=3)  # 1=trivial, 5=major effort
    mapped_file: Optional[str] = None  # populated by Repo Intelligence Agent (Phase 2)
    fix_category: Optional[str] = None  # key into config/fix_categories.yaml
    status: FindingStatus = FindingStatus.OPEN
    is_assumed: bool = False  # true when evidence relies on heuristics, not live measurement
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def autoFixable(self) -> bool:  # noqa: N802 - matches Appendix 15.1 field name intentionally
        return self.fix_type == FixType.AUTO_FIXABLE

    @property
    def priority_score(self) -> float:
        """Impact x effort scoring model referenced in Section 5.2 / FR-2.2.

        Higher is more urgent: weight severity heavily, reward low effort.
        """
        return round((self.impact_score * self.severity.weight) / max(self.effort_score, 1), 2)

    def quadrant(self) -> str:
        high_impact = self.impact_score >= 4 or self.severity in (Severity.CRITICAL, Severity.HIGH)
        low_effort = self.effort_score <= 2
        if high_impact and low_effort:
            return "quick_win"
        if high_impact and not low_effort:
            return "high_impact_high_effort"
        return "low_impact"


class CategoryScore(BaseModel):
    category: Category
    score: int = Field(ge=0, le=100)
    findings_count: int = 0


class AuditRun(BaseModel):
    run_id: str = Field(default_factory=lambda: _short_id("run"))
    target_url: str
    repo_url: Optional[str] = None
    page_limit: int = 50
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    pages_crawled: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    category_scores: list[CategoryScore] = Field(default_factory=list)
    overall_score: int = Field(ge=0, le=100, default=0)
    llm_tokens_used: int = 0
    budget_exceeded: bool = False
    errors: list[str] = Field(default_factory=list)
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    # Phase 2 outcome for UI: not_run | skipped | success | failed
    phase2_status: str = "not_run"
    phase2_message: Optional[str] = None

    def add_finding(self, finding: Finding) -> None:
        self.findings.append(finding)
