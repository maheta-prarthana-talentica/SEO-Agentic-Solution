import type { TraceEntry } from "../api/client";

export default function TraceViewer({ entries }: { entries: TraceEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-ink/15 px-4 py-8 text-center text-ink/50">
        No agent trace found for this run.
      </p>
    );
  }

  return (
    <ol className="space-y-2 font-mono text-xs">
      {entries.map((e, i) => (
        <li
          key={`${e.timestamp}-${i}`}
          className="rounded-lg border border-ink/10 bg-ink px-3 py-2 text-mist"
        >
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <span className="text-mist/50">{e.timestamp}</span>
            <span className="text-sage">{e.agent}</span>
            <span className="text-white">{e.action}</span>
            {e.finding_id && (
              <span className="text-coral">{e.finding_id}</span>
            )}
            <span className="uppercase text-mist/40">{e.level}</span>
          </div>
          {e.detail && Object.keys(e.detail).length > 0 && (
            <pre className="mt-1 overflow-x-auto text-mist/70">
              {JSON.stringify(e.detail, null, 0)}
            </pre>
          )}
        </li>
      ))}
    </ol>
  );
}
