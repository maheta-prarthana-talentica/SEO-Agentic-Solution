import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  type AuditResponse,
  type Category,
  type Finding,
  type FindingBrief,
  type FixType,
  type Severity,
  type StructuredReport,
  type TraceEntry,
} from "../api/client";
import ScoreRing from "../components/ScoreRing";
import FindingsTable from "../components/FindingsTable";
import TraceViewer from "../components/TraceViewer";

export default function RunDetailPage() {
  const { runId } = useParams();
  const [data, setData] = useState<AuditResponse | null>(null);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [category, setCategory] = useState<Category | "all">("all");
  const [fixType, setFixType] = useState<FixType | "all">("all");
  const [tab, setTab] = useState<"summary" | "findings" | "report" | "trace">(
    "summary"
  );

  const [showPhase2, setShowPhase2] = useState(false);
  const [githubRepo, setGithubRepo] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [phase2Busy, setPhase2Busy] = useState(false);
  const [phase2Error, setPhase2Error] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    api
      .getAudit(runId)
      .then(setData)
      .catch((e) => setError(String(e.message || e)));
    api
      .getTrace(runId)
      .then((t) => setTrace(t.entries))
      .catch(() => setTrace([]));
  }, [runId]);

  const filtered: Finding[] = useMemo(() => {
    if (!data) return [];
    return data.run.findings.filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      if (category !== "all" && f.category !== category) return false;
      if (fixType !== "all" && f.fix_type !== fixType) return false;
      return true;
    });
  }, [data, severity, category, fixType]);

  async function onPhase2(e: FormEvent) {
    e.preventDefault();
    if (!runId) return;
    setPhase2Busy(true);
    setPhase2Error(null);
    try {
      const res = await api.runPhase2(runId, {
        github_repo_url: githubRepo.trim(),
        github_token: githubToken.trim(),
      });
      setData(res);
      setShowPhase2(false);
      setTab("summary");
      if (res.phase2_status === "failed") {
        setPhase2Error(res.phase2_message || "Phase 2 failed.");
      }
    } catch (err) {
      setPhase2Error(String((err as Error).message || err));
    } finally {
      setPhase2Busy(false);
    }
  }

  if (error) {
    return <p className="text-coral">{error}</p>;
  }
  if (!data) {
    return <p className="text-ink/60">Loading run…</p>;
  }

  const run = data.run;
  const sr = data.structured_report;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div>
          <Link to="/" className="text-sm text-sea hover:underline">
            ← All runs
          </Link>
          <h1 className="mt-2 text-3xl font-bold break-all">{run.target_url}</h1>
          <p className="mt-1 text-sm text-ink/55">
            {run.run_id} · {run.pages_crawled.length} pages crawled ·{" "}
            {run.findings.length} findings
          </p>
          <Phase2Banner data={data} />
          {run.errors && run.errors.length > 0 && (
            <div className="mt-3 rounded-md border border-coral/30 bg-coral/10 px-3 py-2 text-sm text-coral">
              <p className="font-semibold">Run errors</p>
              <ul className="mt-1 list-disc pl-5">
                {run.errors.map((err) => (
                  <li key={err}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <ScoreRing score={run.overall_score} size={96} label="Overall" />
      </div>

      <div className="grid gap-3 sm:grid-cols-5">
        {run.category_scores.map((cs) => (
          <div
            key={cs.category}
            className="rounded-lg border border-ink/10 bg-white/70 px-3 py-3 text-center"
          >
            <p className="text-xs uppercase tracking-wide text-ink/45">
              {cs.category}
            </p>
            <p className="font-display text-2xl font-semibold text-ink">
              {cs.score}
            </p>
            <p className="text-xs text-ink/45">{cs.findings_count} issues</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-4 border-b border-ink/10 text-sm font-medium">
        {(["summary", "findings", "report", "trace"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`border-b-2 px-1 pb-2 capitalize ${
              tab === t
                ? "border-sea text-sea"
                : "border-transparent text-ink/55 hover:text-ink"
            }`}
          >
            {t === "summary" ? "Suggestions" : t}
          </button>
        ))}
      </div>

      {tab === "summary" && sr && <SuggestionsPanel sr={sr} />}

      {tab === "findings" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-3 text-sm">
            <Select
              label="Severity"
              value={severity}
              onChange={(v) => setSeverity(v as Severity | "all")}
              options={["all", "critical", "high", "medium", "low"]}
            />
            <Select
              label="Category"
              value={category}
              onChange={(v) => setCategory(v as Category | "all")}
              options={[
                "all",
                "technical",
                "on-page",
                "content",
                "structured-data",
                "performance",
              ]}
            />
            <Select
              label="Fix type"
              value={fixType}
              onChange={(v) => setFixType(v as FixType | "all")}
              options={["all", "auto-fixable", "assisted", "manual"]}
            />
          </div>
          <FindingsTable findings={filtered} />
        </div>
      )}

      {tab === "report" && (
        <pre className="overflow-x-auto whitespace-pre-wrap rounded-xl border border-ink/10 bg-white/80 p-5 text-sm leading-relaxed text-ink/90">
          {data.report_markdown}
        </pre>
      )}

      {tab === "trace" && <TraceViewer entries={trace} />}

      {/* Phase 2 continuation */}
      <section className="rounded-xl border border-ink/10 bg-white/80 p-6">
        <h2 className="font-display text-xl font-semibold">
          Proceed to Phase 2?
        </h2>
        <p className="mt-1 text-sm text-ink/60">
          {sr?.phase2_cta ||
            "Optionally map findings to a GitHub repo and open a remediation PR."}
        </p>

        {!showPhase2 ? (
          <button
            type="button"
            onClick={() => setShowPhase2(true)}
            className="mt-4 rounded-md bg-ink px-4 py-2.5 text-sm font-medium text-white hover:bg-ink/90"
          >
            Yes — continue with GitHub code fixes
          </button>
        ) : (
          <form onSubmit={onPhase2} className="mt-4 space-y-3 max-w-lg">
            <label className="block text-sm">
              <span className="font-medium">GitHub repository</span>
              <input
                required
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
                placeholder="owner/repo or https://github.com/owner/repo"
                className="mt-1 w-full rounded-md border border-ink/15 px-3 py-2 outline-none focus:border-sea"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">GitHub token (PAT)</span>
              <input
                required
                type="password"
                autoComplete="off"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder="ghp_…"
                className="mt-1 w-full rounded-md border border-ink/15 px-3 py-2 font-mono text-sm outline-none focus:border-sea"
              />
            </label>
            {phase2Error && (
              <p className="text-sm text-coral">{phase2Error}</p>
            )}
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={phase2Busy}
                className="rounded-md bg-sea px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {phase2Busy ? "Running Phase 2…" : "Run Phase 2"}
              </button>
              <button
                type="button"
                onClick={() => setShowPhase2(false)}
                className="rounded-md border border-ink/15 px-4 py-2 text-sm"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

function Phase2Banner({ data }: { data: AuditResponse }) {
  const status = data.phase2_status || data.run.phase2_status || "not_run";
  const message =
    data.phase2_message || data.run.phase2_message || null;
  const prUrl = data.pr_url || data.run.pr_url || null;
  const branch = data.branch_name || data.run.branch_name || null;

  if (status === "not_run") return null;

  if (status === "success") {
    return (
      <div className="mt-3 rounded-md border border-sage/40 bg-sage/10 px-3 py-2 text-sm text-ink">
        <p className="font-semibold text-sage">Phase 2 succeeded</p>
        <p className="mt-1 text-ink/80">
          {message || "Remediation pull request opened."}
        </p>
        {prUrl && (
          <a
            href={prUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-sea hover:underline"
          >
            Open pull request →
          </a>
        )}
        {branch && (
          <p className="mt-1 text-xs text-ink/50">Branch: {branch}</p>
        )}
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="mt-3 rounded-md border border-coral/40 bg-coral/10 px-3 py-2 text-sm text-coral">
        <p className="font-semibold">Phase 2 failed</p>
        <p className="mt-1">{message || "Could not open a remediation PR."}</p>
        {branch && (
          <p className="mt-1 text-xs opacity-80">
            Branch created: {branch} (no open PR)
          </p>
        )}
      </div>
    );
  }

  // skipped
  return (
    <div className="mt-3 rounded-md border border-ink/15 bg-mist/40 px-3 py-2 text-sm text-ink/70">
      <p className="font-semibold text-ink/80">Phase 2 skipped</p>
      <p className="mt-1">{message || "GitHub credentials were not configured."}</p>
    </div>
  );
}

function SuggestionsPanel({ sr }: { sr: StructuredReport }) {
  return (
    <div className="space-y-8">
      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-sage/30 bg-sage/5 p-5">
          <h3 className="font-display text-lg font-semibold text-sage">
            Key strengths
          </h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {sr.key_strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-coral/30 bg-coral/5 p-5">
          <h3 className="font-display text-lg font-semibold text-coral">
            Key weaknesses
          </h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {sr.key_weaknesses.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">Prioritization</h3>
        <div className="mt-3 grid gap-4 lg:grid-cols-3">
          <BriefList
            title="Quick wins (high impact / low effort)"
            items={sr.quick_wins}
            accent="sea"
          />
          <BriefList
            title="High impact / high effort"
            items={sr.high_impact_high_effort}
            accent="coral"
          />
          <BriefList title="Low impact" items={sr.low_impact} accent="ink" />
        </div>
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">
          Top recommendations
        </h3>
        <ol className="mt-3 space-y-3">
          {sr.top_recommendations.map((f, i) => (
            <li
              key={f.id}
              className="rounded-lg border border-ink/10 bg-white/80 px-4 py-3"
            >
              <p className="font-medium">
                {i + 1}. {f.title}{" "}
                <span className="text-xs font-normal text-ink/45">
                  ({f.severity} · {f.fix_type})
                </span>
              </p>
              <p className="mt-1 text-sm text-ink/70">{f.recommendation}</p>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">
          Phase 2 readiness
        </h3>
        <div className="mt-3 grid gap-4 md:grid-cols-3">
          <BriefList
            title="Safe for automated fixes"
            items={sr.phase2_auto_fixable}
            accent="sage"
          />
          <BriefList
            title="Assisted / review"
            items={sr.phase2_assisted}
            accent="sea"
          />
          <BriefList
            title="Manual intervention"
            items={sr.phase2_manual}
            accent="coral"
          />
        </div>
      </section>
    </div>
  );
}

function BriefList({
  title,
  items,
  accent,
}: {
  title: string;
  items: FindingBrief[];
  accent: "sea" | "coral" | "ink" | "sage";
}) {
  const titleColor = {
    sea: "text-sea",
    coral: "text-coral",
    ink: "text-ink",
    sage: "text-sage",
  }[accent];

  return (
    <div className="rounded-xl border border-ink/10 bg-white/70 p-4">
      <h4 className={`text-sm font-semibold ${titleColor}`}>{title}</h4>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-ink/40">None</p>
      ) : (
        <ul className="mt-2 space-y-2 text-sm">
          {items.map((f) => (
            <li key={f.id}>
              <span className="font-mono text-xs text-ink/40">{f.id}</span>{" "}
              <span className="font-medium">{f.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-ink/55">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-ink/15 bg-white px-2 py-1.5"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
