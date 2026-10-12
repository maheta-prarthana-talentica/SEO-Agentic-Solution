import { useState } from "react";
import type { Finding } from "../api/client";

const severityColor: Record<string, string> = {
  critical: "bg-coral/15 text-coral",
  high: "bg-coral/10 text-coral",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-ink/5 text-ink/60",
};

export default function FindingsTable({ findings }: { findings: Finding[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (findings.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-ink/15 px-4 py-8 text-center text-ink/50">
        No findings match these filters.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-ink/10 overflow-hidden rounded-xl border border-ink/10 bg-white/80">
      {findings.map((f) => {
        const open = openId === f.id;
        return (
          <li key={f.id}>
            <button
              type="button"
              onClick={() => setOpenId(open ? null : f.id)}
              className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-mist/60"
            >
              <span className="font-mono text-xs text-ink/40">{f.id}</span>
              <span className="flex-1 font-medium text-ink">{f.title}</span>
              <span
                className={`rounded px-2 py-0.5 text-xs font-medium capitalize ${
                  severityColor[f.severity] || ""
                }`}
              >
                {f.severity}
              </span>
              <span className="text-xs capitalize text-ink/45">{f.fix_type}</span>
            </button>
            {open && (
              <div className="space-y-2 bg-mist/40 px-4 pb-4 text-sm text-ink/80">
                <p>
                  <strong>Category:</strong> {f.category}
                </p>
                <p>
                  <strong>Description:</strong> {f.description}
                </p>
                <p>
                  <strong>Evidence:</strong> {f.evidence}
                </p>
                <p>
                  <strong>Recommended fix:</strong> {f.recommendation}
                </p>
                <p>
                  <strong>Affected:</strong>{" "}
                  {f.affected_pages.slice(0, 5).join(", ") || "Site-wide"}
                  {f.affected_pages.length > 5
                    ? ` (+${f.affected_pages.length - 5} more)`
                    : ""}
                </p>
                {f.mapped_file && (
                  <p>
                    <strong>Mapped file:</strong>{" "}
                    <code className="text-xs">{f.mapped_file}</code>
                  </p>
                )}
                {f.is_assumed && (
                  <p className="text-amber-700">Note: metrics/evidence are assumed.</p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
