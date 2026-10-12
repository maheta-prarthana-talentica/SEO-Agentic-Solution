"""Structured, traceable logging for every agent decision and tool call.

Satisfies the "Auditability" NFR: every agent decision and tool call is logged with
timestamps and linked to the originating finding/run. Each log line is a single JSON
object so it can be tailed, grepped, or loaded into the dashboard's trace viewer
(`backend/api/routes_reports.py::get_trace`).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class TraceLogger:
    """Per-run structured trace logger.

    Usage:
        trace = TraceLogger(run_id)
        trace.log(agent="TechnicalSEOAgent", action="parse_robots_txt", finding_id="F-abc123",
                   detail={"disallow_rules": 3})
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._path = LOG_DIR / f"{run_id}.jsonl"
        self._logger = logging.getLogger(f"seo_agent.{run_id}")
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def log(self, agent: str, action: str, detail: dict[str, Any] | None = None,
             finding_id: str | None = None, level: str = "info") -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "action": action,
            "finding_id": finding_id,
            "detail": detail or {},
            "level": level,
        }
        line = json.dumps(entry, default=str)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        getattr(self._logger, level, self._logger.info)(line)

    def read_trace(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
