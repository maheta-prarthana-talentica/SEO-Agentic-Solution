"""Orchestrator Agent — LangGraph coordinator (Section 5.2).

Plans the audit-to-fix workflow and delegates to specialized sub-agents.
Falls back to a plain sequential runner if langgraph is not installed, so the
pipeline stays demoable offline.
"""
from __future__ import annotations

import os
from typing import Any

from backend.models import AuditRun
from agents.state import PipelineState, RunConfig
from agents import crawl_audit_agent
from agents import technical_seo_agent
from agents import content_onpage_agent
from agents import structured_data_agent
from agents import performance_agent
from agents import reporting_agent
from tools.llm_client import LLMClient, BudgetExceededError
from tools.logging_utils import TraceLogger

try:
    from langgraph.graph import END, StateGraph  # type: ignore

    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LANGGRAPH_AVAILABLE = False


def build_run_config(
    target_url: str,
    *,
    repo_url: str | None = None,
    github_token: str | None = None,
    page_limit: int | None = None,
    use_fixture: bool = False,
) -> RunConfig:
    from tools.github_client import normalize_github_token

    token = normalize_github_token(github_token or os.getenv("GITHUB_TOKEN") or "") or None
    return RunConfig(
        target_url=target_url if not use_fixture else "https://fixture.example.com",
        repo_url=repo_url or os.getenv("GITHUB_REPO") or None,
        github_token=token,
        github_token_configured=bool(token),
        page_limit=page_limit or int(os.getenv("MAX_PAGES_PER_CRAWL", "50")),
        use_fixture=use_fixture,
    )


def run_audit(
    target_url: str = "https://example.com",
    *,
    repo_url: str | None = None,
    github_token: str | None = None,
    page_limit: int | None = None,
    use_fixture: bool = False,
    enable_remediation: bool = False,
) -> tuple[AuditRun, str]:
    """Top-level entry: runs Phase 1 audit (always) and optionally Phases 2-4."""
    config = build_run_config(
        target_url,
        repo_url=repo_url,
        github_token=github_token,
        page_limit=page_limit,
        use_fixture=use_fixture,
    )
    run = AuditRun(target_url=config["target_url"], repo_url=config["repo_url"],
                   page_limit=config["page_limit"])
    trace = TraceLogger(run.run_id)
    llm = LLMClient(run.run_id, trace_logger=trace)

    state: PipelineState = {
        "config": config,
        "run": run,
        "errors": [],
    }

    # Always use the sequential pipeline. The experimental LangGraph graph drops
    # crawl metadata between nodes (KeyError: 'robots') and does not yet include
    # remediation nodes — Phase 2 must go through _run_sequential.
    final = _run_sequential(state, llm, trace, enable_remediation=enable_remediation)

    return final["run"], final.get("report_markdown") or ""


def _run_sequential(
    state: PipelineState,
    llm: LLMClient,
    trace: TraceLogger,
    *,
    enable_remediation: bool,
) -> PipelineState:
    config = state["config"]
    run = state["run"]

    # --- Phase 1: crawl + parallel-ish audit agents ---
    try:
        crawl = crawl_audit_agent.run(
            config["target_url"],
            page_limit=config["page_limit"],
            use_fixture=config["use_fixture"],
            trace=trace,
        )
    except Exception as exc:  # noqa: BLE001
        state.setdefault("errors", []).append(f"crawl failed: {exc}")
        run.errors.append(str(exc))
        trace.log("Orchestrator", "crawl_failed", {"error": str(exc)}, level="error")
        _, md = reporting_agent.compile_report(run, [], llm=llm, trace=trace)
        state["report_markdown"] = md
        return state

    state["crawl_pages"] = crawl.pages
    run.pages_crawled = [p.url for p in crawl.pages]

    tech = technical_seo_agent.run(crawl.base_url, crawl.pages, crawl.robots, crawl.sitemap)
    onpage = content_onpage_agent.run_onpage(crawl.pages)
    try:
        content = content_onpage_agent.run_content_quality(crawl.pages, llm=llm)
    except BudgetExceededError as exc:
        content = []
        run.budget_exceeded = True
        run.errors.append(str(exc))
        trace.log("Orchestrator", "budget_exceeded", {"error": str(exc)}, level="warning")
    schema = structured_data_agent.run(crawl.pages)
    perf = performance_agent.run(crawl.pages, crawl.core_web_vitals, crawl.base_url)

    state["technical_findings"] = tech
    state["onpage_findings"] = onpage
    state["content_findings"] = content
    state["structured_data_findings"] = schema
    state["performance_findings"] = perf

    all_findings = tech + onpage + content + schema + perf
    pr_url = None
    branch_name = None

    # --- Phases 2-4 (optional) ---
    if enable_remediation and config.get("github_token_configured") and config.get("repo_url"):
        try:
            from agents import repo_intelligence_agent
            from agents import code_remediation_agent
            from agents import verification_agent
            from agents import github_integration_agent

            repo_info = repo_intelligence_agent.run(
                config["repo_url"], all_findings, trace=trace
            )
            state["repo_index"] = repo_info.get("index")
            state["repo_conventions"] = repo_info.get("conventions")
            state["framework"] = repo_info.get("framework")
            all_findings = repo_info.get("findings", all_findings)

            if not repo_info.get("repo_path"):
                msg = (
                    "Phase 2 failed: could not clone/index the repo. "
                    "Check that the PAT has Contents (read/write) on "
                    f"{config['repo_url']}."
                )
                state.setdefault("errors", []).append(msg)
                run.errors.append(msg)
                run.phase2_status = "failed"
                run.phase2_message = msg
            else:
                diffs = code_remediation_agent.run(
                    all_findings,
                    repo_info.get("repo_path"),
                    repo_info.get("conventions") or {},
                    llm=llm,
                    trace=trace,
                )
                state["proposed_diffs"] = diffs

                verified = verification_agent.run(diffs, repo_info.get("repo_path"), trace=trace)
                state["verification_results"] = verified

                gh = github_integration_agent.run(
                    repo_url=config["repo_url"],
                    run_id=run.run_id,
                    diffs=verified,
                    findings=all_findings,
                    github_token=config.get("github_token"),
                    trace=trace,
                )
                state["branch_name"] = gh.get("branch_name")
                state["pr_url"] = gh.get("pr_url")
                pr_url = gh.get("pr_url")
                branch_name = gh.get("branch_name")
                run.phase2_status = gh.get("status") or ("success" if pr_url else "failed")
                run.phase2_message = gh.get("message") or gh.get("error")
                if gh.get("error"):
                    msg = f"GitHub PR step failed: {gh['error']}"
                    state.setdefault("errors", []).append(msg)
                    run.errors.append(msg)
                    trace.log("Orchestrator", "github_pr_failed",
                              {"error": gh["error"]}, level="error")
        except Exception as exc:  # noqa: BLE001
            msg = f"Phase 2 failed: {exc}"
            state.setdefault("errors", []).append(msg)
            run.errors.append(msg)
            run.phase2_status = "failed"
            run.phase2_message = msg
            trace.log("Orchestrator", "remediation_failed", {"error": str(exc)}, level="error")
    elif enable_remediation:
        msg = "Phase 2 skipped: GitHub token and/or repository URL not configured."
        state.setdefault("errors", []).append(msg)
        run.errors.append(msg)
        run.phase2_status = "skipped"
        run.phase2_message = msg
        trace.log("Orchestrator", "remediation_skipped", {"reason": msg}, level="warning")
    else:
        run.phase2_status = "not_run"
        run.phase2_message = "Phase 2 was not requested for this run."

    run.pr_url = pr_url
    run.branch_name = branch_name
    run, md = reporting_agent.compile_report(
        run, all_findings, llm=llm, trace=trace, pr_url=pr_url
    )
    state["run"] = run
    state["report_markdown"] = md
    return state


def _build_full_graph() -> Any:
    """LangGraph wiring for the full pipeline when the package is available."""
    from agents import repo_intelligence_agent
    from agents import code_remediation_agent
    from agents import verification_agent
    from agents import github_integration_agent

    def node_crawl(state: PipelineState) -> PipelineState:
        config = state["config"]
        trace = TraceLogger(state["run"].run_id)
        crawl = crawl_audit_agent.run(
            config["target_url"], page_limit=config["page_limit"],
            use_fixture=config["use_fixture"], trace=trace,
        )
        state["crawl_pages"] = crawl.pages
        state["run"].pages_crawled = [p.url for p in crawl.pages]
        # Stash robot/sitemap/cwv on state via a temporary attribute dict
        state["_crawl_meta"] = {  # type: ignore[typeddict-unknown-key]
            "robots": crawl.robots, "sitemap": crawl.sitemap,
            "cwv": crawl.core_web_vitals, "base_url": crawl.base_url,
        }
        return state

    def node_audit(state: PipelineState) -> PipelineState:
        meta = state.get("_crawl_meta") or {}  # type: ignore[arg-type]
        pages = state.get("crawl_pages") or []
        if "robots" not in meta or "sitemap" not in meta:
            # Crawl meta was dropped from graph state — re-fetch so we never KeyError.
            from tools.robots_sitemap import analyze_robots_txt, analyze_sitemap_xml
            base = state["config"]["target_url"]
            robots = analyze_robots_txt(base)
            sitemap = analyze_sitemap_xml(
                base, robots.sitemap_urls[0] if robots.sitemap_urls else None
            )
            meta = {
                "robots": robots,
                "sitemap": sitemap,
                "cwv": None,
                "base_url": base,
            }
        llm = LLMClient(state["run"].run_id)
        state["technical_findings"] = technical_seo_agent.run(
            meta.get("base_url", state["config"]["target_url"]), pages,
            meta["robots"], meta["sitemap"],
        )
        state["onpage_findings"] = content_onpage_agent.run_onpage(pages)
        state["content_findings"] = content_onpage_agent.run_content_quality(pages, llm=llm)
        state["structured_data_findings"] = structured_data_agent.run(pages)
        state["performance_findings"] = performance_agent.run(
            pages, meta.get("cwv"), meta.get("base_url", state["config"]["target_url"])
        )
        return state

    def node_report(state: PipelineState) -> PipelineState:
        all_findings = (
            (state.get("technical_findings") or [])
            + (state.get("onpage_findings") or [])
            + (state.get("content_findings") or [])
            + (state.get("structured_data_findings") or [])
            + (state.get("performance_findings") or [])
        )
        llm = LLMClient(state["run"].run_id)
        run, md = reporting_agent.compile_report(
            state["run"], all_findings, llm=llm, pr_url=state.get("pr_url")
        )
        state["run"] = run
        state["report_markdown"] = md
        return state

    g = StateGraph(PipelineState)
    g.add_node("crawl", node_crawl)
    g.add_node("audit", node_audit)
    g.add_node("report", node_report)
    g.set_entry_point("crawl")
    g.add_edge("crawl", "audit")
    g.add_edge("audit", "report")
    g.add_edge("report", END)
    return g.compile()
