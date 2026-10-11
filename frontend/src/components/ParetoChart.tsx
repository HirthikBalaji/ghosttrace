import type { ParetoPoint } from "../types";

// Price of Certainty: total cost J*(k) of the cheapest plan that is k-robust.
export function ParetoChart({ points, selected, onSelect }: { points: ParetoPoint[]; selected: number; onSelect: (k: number) => void }) {
  const feas = points.filter((p) => p.feasible && p.total_cost !== null);
  const W = 520, H = 240, L = 54, R = 20, T = 18, B = 42;
  const maxK = Math.max(1, ...points.map((p) => p.k));
  const maxC = Math.max(1, ...feas.map((p) => p.total_cost as number)) * 1.15;
  const x = (k: number) => L + (k / maxK) * (W - L - R);
  const y = (c: number) => H - B - (c / maxC) * (H - T - B);
  const step = feas.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.k)},${y(p.total_cost as number)}`).join(" ");
  return (
    <figure className="pareto" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-labelledby="pareto-title" aria-describedby="pareto-desc">
        <title id="pareto-title">Price of Certainty curve</title>
        <desc id="pareto-desc">{points.map((p) => `k=${p.k}: ${p.feasible ? `cost ${p.total_cost}` : "infeasible"}`).join("; ")}</desc>
        <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="var(--line)" />
        <line x1={L} y1={T} x2={L} y2={H - B} stroke="var(--line)" />
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(maxC * f)} y2={y(maxC * f)} stroke="var(--line)" strokeDasharray="2 4" />
            <text x={L - 8} y={y(maxC * f) + 4} textAnchor="end">{Math.round(maxC * f)}</text>
          </g>
        ))}
        {points.map((p) => <text key={p.k} x={x(p.k)} y={H - B + 18} textAnchor="middle">k = {p.k}</text>)}
        <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle">robustness level k (unverified edges an attacker needs)</text>
        <text x={14} y={(T + H - B) / 2} textAnchor="middle" transform={`rotate(-90 14 ${(T + H - B) / 2})`}>total cost J</text>
        <path d={step} fill="none" stroke="var(--accent)" strokeWidth={2.5} />
        {points.map((p) =>
          p.feasible && p.total_cost !== null ? (
            <g key={p.k} className="pt" tabIndex={0} role="button" aria-label={`Select k=${p.k} plan, cost ${p.total_cost}`}
              aria-pressed={selected === p.k} onClick={() => onSelect(p.k)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(p.k)}>
              <circle cx={x(p.k)} cy={y(p.total_cost)} r={selected === p.k ? 9 : 6} fill={selected === p.k ? "var(--accent)" : "var(--panel)"}
                stroke="var(--accent)" strokeWidth={2.5} />
              <text x={x(p.k)} y={y(p.total_cost) - 14} textAnchor="middle" style={{ fontWeight: 650 }}>{p.total_cost}</text>
            </g>
          ) : (
            <g key={p.k}><text x={x(p.k)} y={T + 14} textAnchor="middle" style={{ fill: "var(--bad)" }}>✕ infeasible</text></g>
          ),
        )}
      </svg>
      <figcaption className="small muted">
        Each point is the cheapest plan the solver found that leaves no CONFIRMED path and needs more than k unverified edges to reopen.
        Optimality: {points.map((p) => `k=${p.k} ${p.optimality.replace("_", " ")}`).join(" · ")} (within the declared candidate set). Click a point to inspect.
      </figcaption>
    </figure>
  );
}
