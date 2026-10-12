import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AuditListItem } from "../api/client";
import ScoreRing from "../components/ScoreRing";

export default function HomePage() {
  const [items, setItems] = useState<AuditListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listAudits()
      .then(setItems)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-8">
      <section className="max-w-2xl">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Audit runs</h1>
        <p className="mt-2 text-ink/70">
          Phase 1: enter a website URL to get SEO suggestions. Phase 2 (optional): connect
          GitHub to apply auto-fixable changes via a pull request.
        </p>
        <Link
          to="/new"
          className="mt-4 inline-block rounded-md bg-sea px-5 py-2.5 text-sm font-medium text-white hover:bg-sea/90"
        >
          New audit — enter URL
        </Link>
      </section>

      {loading && <p className="text-ink/60">Loading runs…</p>}
      {error && (
        <p className="rounded-md border border-coral/30 bg-coral/10 px-4 py-3 text-sm text-coral">
          Could not load audits. Is the API running on :8000? {error}
        </p>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="rounded-xl border border-dashed border-ink/20 bg-white/50 px-6 py-12 text-center">
          <p className="font-display text-xl">No runs yet</p>
          <p className="mt-2 text-ink/60">
            Paste a website URL on the New audit page to run Phase 1 and see suggestions.
          </p>
          <Link
            to="/new"
            className="mt-6 inline-block rounded-md bg-sea px-5 py-2.5 text-sm font-medium text-white hover:bg-sea/90"
          >
            Enter website URL
          </Link>
        </div>
      )}

      <ul className="grid gap-4 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.run_id}>
            <Link
              to={`/runs/${item.run_id}`}
              className="flex items-center gap-5 rounded-xl border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:border-sea/40 hover:shadow-md"
            >
              <ScoreRing score={item.overall_score} size={64} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink">{item.target_url}</p>
                <p className="mt-1 text-sm text-ink/55">
                  {item.findings_count} findings · {item.run_id}
                </p>
                {item.completed_at && (
                  <p className="text-xs text-ink/40">
                    {new Date(item.completed_at).toLocaleString()}
                  </p>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
