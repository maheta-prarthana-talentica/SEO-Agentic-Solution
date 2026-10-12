# SEO Agentic Solutions -- POC

An autonomous multi-agent system for website SEO auditing, optimization, and (in later phases) direct
codebase remediation via GitHub pull requests. This implements the design in
[`docs/SEO_Agentic_Solutions_Requirements_Talentica_POC 1.docx`](../SEO_Agentic_Solutions_Requirements_Talentica_POC%201.docx).

## What's implemented

| Phase | Area | Status |
|---|---|---|
| 0 | Scaffold, config, orchestrator skeleton | Done |
| 1 | Crawl / Technical SEO / Content & On-Page / Structured Data agents + Reporting Agent | Done |
| 2 | Repo Intelligence Agent (repo indexing + finding-to-file mapping) | Done |
| 3 | Code Remediation Agent + Verification Agent | Done |
| 4 | GitHub Integration Agent (branch/commit/PR + guardrails) | Done |
| 5 | React dashboard | Done |

Everything runs **audit-only by default**. Nothing writes to a GitHub repo unless you explicitly run the
remediation pipeline with a configured `GITHUB_TOKEN` and target repo.

## Repository layout

```
/agents      orchestrator + each sub-agent's logic and prompts (LangGraph nodes)
/tools       crawler, PSI client, schema validator, repo scanner, diff engine, GitHub client, LLM client
/rag         SEO knowledge base + vector store config used to ground agent reasoning
/backend     FastAPI service exposing the orchestrator as an HTTP API
/dashboard   React + Vite + TypeScript reporting frontend
/config      denylist, fix-category automation levels, LLM budget caps
/docs        requirements doc + the prompt library for every agent
/tests       unit tests + a static fixture "sample site" used for offline demos
/scripts     CLI entry points (e.g. run a full audit against any URL)
```

## Prerequisites

This POC was authored in an environment **without Python/Node installed**, so none of the code below has
been executed yet. To run it you need:

- Python 3.11+
- Node.js 18+ (for the dashboard)
- (Optional) `ANTHROPIC_API_KEY` for Claude, **or** local [Ollama](https://ollama.com) (`ollama pull llama3.2`) for a free LLM. Without either, heuristics still produce a full audit report.
- (Optional) `GITHUB_TOKEN` + `PSI_API_KEY` for remediation PRs and live Core Web Vitals.

## Setup

```powershell
# 1. Backend
python -m venv .venv
.venv\Scripts\Activate.ps1
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
pip install -r requirements.txt
playwright install chromium   # optional, only needed for JS-rendered CWV checks
copy .env.example .env        # then fill in API keys
uvicorn backend.main:app --reload --port 8000

# 2. Run a one-off audit from the CLI (no server needed)
python scripts/run_demo_audit.py --url https://example.com

# 3. Dashboard
cd dashboard
npm install
npm run dev
```

## Running the demo (no live site or API keys required)

`scripts/run_demo_audit.py --fixture` runs the full Phase 1 audit pipeline against the static fixture site in
`tests/fixtures/sample_site/`, which intentionally contains the common SEO issues this system detects (missing
meta description, duplicate titles, missing alt text, no structured data, etc.). This is how the exact report
format was validated before wiring the agents to a live crawl, as called for in the implementation plan.

```powershell
python scripts/run_demo_audit.py --fixture
```

This prints the structured audit report (Summary, Detailed Findings, Prioritization, Top Recommendations,
Phase 2 Readiness) to stdout and writes it to `reports/<run_id>.json` and `reports/<run_id>.md`.

## Graceful degradation

Every component that depends on an external service or paid API degrades rather than failing the run:

### LLM cascade (`tools/llm_client.py`)
1. **Anthropic (Claude)** — if `ANTHROPIC_API_KEY` is set  
2. **Ollama** (free, local, no key) — if Anthropic has no key or the call fails  
3. **Heuristic / rule-based logic** — if Ollama is down or the model is missing  

```powershell
# Free local LLM setup (optional)
# 1. Install Ollama from https://ollama.com
# 2. Pull a model, then keep Ollama running
ollama pull llama3.2
```

Defaults: `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=llama3.2` (override in `.env`).

### Other fallbacks
- No `PSI_API_KEY` -> Core Web Vitals reported as clearly-labeled **assumed** heuristics.
- Playwright not installed -> plain HTTP + HTML-parse crawl.
- No `GITHUB_TOKEN` -> Phase 2-4 skipped; findings stay recommendation-only.

## Safety guardrails (Section 6.4 / 11 of the requirements doc)

- `config/denylist.yaml` is enforced in code (`tools/diff_utils.py::enforce_denylist`), not just prompted.
- `config/budget.yaml` caps LLM token usage per run; `tools/llm_client.py` halts and flags for review when hit.
- All crawled page content is treated as **untrusted data** -- see `agents/content_onpage_agent.py` docstring
  and `tools/llm_client.py::sanitize_untrusted_text`. It is never concatenated into a system/instruction prompt.
- No auto-merge anywhere in the codebase. `tools/github_client.py` only opens PRs; merging is a manual GitHub
  action by a human reviewer.
