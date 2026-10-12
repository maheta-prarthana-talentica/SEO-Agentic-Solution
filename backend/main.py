"""FastAPI application entrypoint (backend/API layer per Section 9)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(ROOT / ".env")

from backend.api.routes_audit import router as audit_router
from backend.api.routes_reports import router as reports_router

app = FastAPI(
    title="SEO Agentic Solutions API",
    description="Orchestrator endpoints for crawl/audit/remediation runs (Talentica POC).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit_router, prefix="/api")
app.include_router(reports_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
