"""Report + agent-trace endpoints (FR-6.4)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from tools.logging_utils import TraceLogger

router = APIRouter(tags=["reports"])

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"


@router.get("/reports/{run_id}")
def get_report_markdown(run_id: str):
    path = REPORTS / f"{run_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return {"run_id": run_id, "markdown": path.read_text(encoding="utf-8")}


@router.get("/traces/{run_id}")
def get_trace(run_id: str):
    logger = TraceLogger(run_id)
    entries = logger.read_trace()
    if not entries:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"run_id": run_id, "entries": entries}
