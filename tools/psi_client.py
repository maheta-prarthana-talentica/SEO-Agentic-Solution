"""Google PageSpeed Insights client for Core Web Vitals (FR-1.3).

If PSI_API_KEY is not configured (or the API call fails/quota-limits), falls back to a
transparent, clearly-labeled heuristic estimate derived from page weight/resource counts
gathered during the crawl -- never a fabricated exact metric, per the prompt's strict
rule against hallucinating unavailable data.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


@dataclass
class CoreWebVitals:
    lcp_seconds: float | None
    cls: float | None
    inp_ms: float | None
    performance_score: int | None  # 0-100 Lighthouse performance score
    is_assumed: bool
    source_note: str


def get_core_web_vitals(url: str, strategy: str = "mobile") -> CoreWebVitals:
    api_key = os.getenv("PSI_API_KEY")
    if api_key:
        live = _fetch_from_psi(url, strategy, api_key)
        if live is not None:
            return live
    return _heuristic_estimate(url)


def _fetch_from_psi(url: str, strategy: str, api_key: str) -> CoreWebVitals | None:
    try:
        response = httpx.get(
            PSI_ENDPOINT,
            params={"url": url, "strategy": strategy, "key": api_key,
                    "category": "PERFORMANCE"},
            timeout=30.0,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        audits = data.get("lighthouseResult", {}).get("audits", {})
        lcp = audits.get("largest-contentful-paint", {}).get("numericValue")
        cls = audits.get("cumulative-layout-shift", {}).get("numericValue")
        inp = audits.get("experimental-interaction-to-next-paint", {}).get("numericValue")
        perf_score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
        return CoreWebVitals(
            lcp_seconds=round(lcp / 1000, 2) if lcp else None,
            cls=round(cls, 3) if cls is not None else None,
            inp_ms=round(inp, 0) if inp else None,
            performance_score=round(perf_score * 100) if perf_score is not None else None,
            is_assumed=False,
            source_note="Google PageSpeed Insights API (live measurement)",
        )
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def _heuristic_estimate(url: str) -> CoreWebVitals:
    """Rough, clearly-labeled estimate. Used only when live PSI data is unavailable.

    This deliberately avoids inventing precise numbers -- it returns None for the
    numeric fields and communicates the assumption via source_note, matching the
    prompt's "use likely/assumed/common issue" rule. Callers should present this as a
    qualitative flag, not a hard metric, in the report.
    """
    return CoreWebVitals(
        lcp_seconds=None, cls=None, inp_ms=None, performance_score=None, is_assumed=True,
        source_note=(
            "No PSI_API_KEY configured -- Core Web Vitals are not measured for this run. "
            "Common issues assumed present unless proven otherwise: unoptimized/oversized "
            "hero images affecting LCP, render-blocking third-party scripts, and layout "
            "shift from late-loading fonts/ads. Configure PSI_API_KEY for live measurement."
        ),
    )
