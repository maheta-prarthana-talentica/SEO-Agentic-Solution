import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function NewAuditPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [pageLimit, setPageLimit] = useState(25);
  const [fixture, setFixture] = useState(false);

  const [enablePhase2, setEnablePhase2] = useState(false);
  const [githubRepo, setGithubRepo] = useState("");
  const [githubToken, setGithubToken] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    if (!fixture && !url.trim()) {
      setError("Please enter a website URL for Phase 1.");
      setBusy(false);
      return;
    }
    if (enablePhase2) {
      if (!githubRepo.trim()) {
        setError("Phase 2 requires a GitHub repo URL (owner/name or https://github.com/owner/name).");
        setBusy(false);
        return;
      }
      if (!githubToken.trim()) {
        setError("Phase 2 requires a GitHub personal access token.");
        setBusy(false);
        return;
      }
    }

    try {
      const res = await api.runAudit({
        url: fixture ? "https://fixture.example.com" : url.trim(),
        use_fixture: fixture,
        page_limit: pageLimit,
        enable_phase2: enablePhase2,
        enable_remediation: enablePhase2,
        github_repo_url: enablePhase2 ? githubRepo.trim() : undefined,
        github_token: enablePhase2 ? githubToken.trim() : undefined,
      });
      navigate(`/runs/${res.run_id}`);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-4xl font-bold">New SEO audit</h1>
        <p className="mt-2 text-ink/70">
          Start with <strong>Phase 1</strong> (crawl + suggestions). Optionally enable{" "}
          <strong>Phase 2</strong> to map findings to a GitHub repo and open a PR.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-6">
        {/* -------- Phase 1 -------- */}
        <section className="space-y-4 rounded-xl border border-sea/25 bg-white/90 p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-sea text-sm font-bold text-white">
              1
            </span>
            <div>
              <h2 className="font-display text-xl font-semibold">Phase 1 — Website audit</h2>
              <p className="text-sm text-ink/55">Required. Enter any public website URL.</p>
            </div>
          </div>

          <label className="block text-sm">
            <span className="font-medium">Website URL</span>
            <input
              type="url"
              placeholder="https://www.example.com"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (e.target.value) setFixture(false);
              }}
              disabled={fixture}
              required={!fixture}
              className="mt-1 w-full rounded-md border border-ink/15 bg-white px-3 py-2.5 text-base outline-none focus:border-sea disabled:bg-mist/50"
            />
          </label>

          <div className="flex flex-wrap items-end gap-4">
            <label className="block text-sm">
              <span className="font-medium">Page limit</span>
              <input
                type="number"
                min={1}
                max={100}
                value={pageLimit}
                onChange={(e) => setPageLimit(Number(e.target.value) || 25)}
                className="mt-1 w-28 rounded-md border border-ink/15 bg-white px-3 py-2 outline-none focus:border-sea"
              />
            </label>

            <label className="flex items-center gap-2 pb-2 text-sm text-ink/70">
              <input
                type="checkbox"
                checked={fixture}
                onChange={(e) => setFixture(e.target.checked)}
              />
              Use offline demo fixture (no live crawl)
            </label>
          </div>
        </section>

        {/* -------- Phase 2 (optional) -------- */}
        <section className="space-y-4 rounded-xl border border-ink/10 bg-white/80 p-6 shadow-sm">
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              className="mt-1.5"
              checked={enablePhase2}
              onChange={(e) => setEnablePhase2(e.target.checked)}
            />
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-ink/10 text-sm font-bold text-ink">
                  2
                </span>
                <div>
                  <h2 className="font-display text-xl font-semibold">
                    Phase 2 — GitHub code fixes{" "}
                    <span className="text-sm font-normal text-ink/45">(optional)</span>
                  </h2>
                  <p className="text-sm text-ink/55">
                    Map findings to source files, generate diffs, open a pull request.
                    Leave unchecked to only get suggestions.
                  </p>
                </div>
              </div>
            </div>
          </label>

          {enablePhase2 && (
            <div className="space-y-4 border-t border-ink/10 pt-4">
              <label className="block text-sm">
                <span className="font-medium">GitHub repository</span>
                <input
                  type="text"
                  required={enablePhase2}
                  value={githubRepo}
                  onChange={(e) => setGithubRepo(e.target.value)}
                  placeholder="owner/repo or https://github.com/owner/repo"
                  className="mt-1 w-full rounded-md border border-ink/15 bg-white px-3 py-2.5 outline-none focus:border-sea"
                />
              </label>

              <label className="block text-sm">
                <span className="font-medium">GitHub token (PAT)</span>
                <input
                  type="password"
                  required={enablePhase2}
                  autoComplete="off"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  placeholder="ghp_… or fine-grained token"
                  className="mt-1 w-full rounded-md border border-ink/15 bg-white px-3 py-2.5 font-mono text-sm outline-none focus:border-sea"
                />
                <span className="mt-1 block text-xs text-ink/45">
                  Used only for this run (not stored). Needs contents + pull requests + metadata
                  scopes on a single repo. Never commits to main; opens a PR for review.
                </span>
              </label>
            </div>
          )}
        </section>

        {error && (
          <p className="rounded-md border border-coral/30 bg-coral/10 px-3 py-2 text-sm text-coral">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-sea px-4 py-3 text-sm font-semibold text-white transition hover:bg-sea/90 disabled:opacity-60"
        >
          {busy
            ? enablePhase2
              ? "Running Phase 1 + Phase 2…"
              : "Running Phase 1 audit…"
            : enablePhase2
              ? "Run Phase 1 + Phase 2"
              : "Run Phase 1 audit"}
        </button>
      </form>
    </div>
  );
}
