type Props = { score: number; size?: number; label?: string };

export default function ScoreRing({ score, size = 72, label }: Props) {
  const stroke = 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score));
  const offset = c - (pct / 100) * c;
  const color =
    pct >= 80 ? "#3d7a5c" : pct >= 55 ? "#1a6b8a" : "#c45c26";

  return (
    <div className="relative inline-flex flex-col items-center" style={{ width: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(15,28,46,0.1)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div
        className="absolute inset-0 flex flex-col items-center justify-center"
        style={{ transform: "none" }}
      >
        <span className="font-display text-lg font-bold leading-none">{pct}</span>
        {label && <span className="text-[10px] uppercase text-ink/45">{label}</span>}
      </div>
    </div>
  );
}
