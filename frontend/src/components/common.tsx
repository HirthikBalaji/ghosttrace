import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const run = useCallback(() => {
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => my === seq.current && setData(d))
      .catch((e: Error) => my === seq.current && setError(e.message))
      .finally(() => my === seq.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, error, loading, reload: run, setData };
}

export function State({ loading, error, empty, onRetry, children }: {
  loading?: boolean; error?: string | null; empty?: string | false; onRetry?: () => void; children?: ReactNode;
}) {
  if (error)
    return (
      <div className="state err" role="alert">
        <p>Something went wrong: {error}</p>
        {onRetry && <button className="btn" onClick={onRetry}>Retry</button>}
      </div>
    );
  if (loading) return <div className="state" aria-busy="true">Loading…</div>;
  if (empty) return <div className="state">{empty}</div>;
  return <>{children}</>;
}

const CLASS_META: Record<string, { cls: string; icon: string; text: string }> = {
  OBSERVED: { cls: "b-ok", icon: "●", text: "OBSERVED" },
  DERIVED: { cls: "b-derived", icon: "◆", text: "DERIVED" },
  LATENT: { cls: "b-latent", icon: "◌", text: "LATENT" },
  CONFIRMED: { cls: "b-ok", icon: "✔", text: "CONFIRMED" },
  TEMPORALLY_UNCERTAIN: { cls: "b-warn", icon: "⧗", text: "TEMPORALLY UNCERTAIN" },
  UNCERTAIN: { cls: "b-warn", icon: "⧗", text: "VALIDITY UNKNOWN" },
  INACTIVE: { cls: "b-neutral", icon: "○", text: "INACTIVE AT T" },
};
const FLAG_META: Record<string, { cls: string; icon: string; text: string }> = {
  disputed: { cls: "b-warn", icon: "⚠", text: "disputed" },
  stale: { cls: "b-neutral", icon: "⏳", text: "stale" },
  superseded: { cls: "b-neutral", icon: "↻", text: "superseded" },
  weakly_supported: { cls: "b-warn", icon: "◔", text: "weakly supported" },
  possible_false_flag: { cls: "b-bad", icon: "⚑", text: "possible false flag" },
};

export function ClassBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="badge b-neutral">n/a</span>;
  const m = CLASS_META[value] ?? (value.startsWith("CONDITIONAL")
    ? { cls: "b-latent", icon: "◌", text: value.replace("CONDITIONAL", "CONDITIONAL ") }
    : { cls: "b-neutral", icon: "•", text: value });
  return <span className={`badge ${m.cls}`}><span aria-hidden="true">{m.icon}</span>{m.text}</span>;
}

export function FlagBadges({ flags }: { flags?: string[] }) {
  if (!flags?.length) return null;
  return (
    <>
      {flags.map((f) => {
        const m = FLAG_META[f] ?? { cls: "b-neutral", icon: "•", text: f };
        return <span key={f} className={`badge ${m.cls}`}><span aria-hidden="true">{m.icon}</span>{m.text}</span>;
      })}
    </>
  );
}

const STATUS: Record<string, string> = {
  completed: "b-ok", contained: "b-ok", supported: "b-ok", proven_optimal: "b-ok", running: "b-accent",
  queued: "b-neutral", created: "b-neutral", partially_supported: "b-warn", bounded: "b-warn", heuristic: "b-warn",
  disputed: "b-bad", failed: "b-bad", not_contained: "b-bad", cancelled: "b-neutral", insufficient_evidence: "b-warn",
  simulated: "b-accent", proposed: "b-neutral", approved: "b-ok", blocked: "b-warn",
};
export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge ${STATUS[value] ?? "b-neutral"}`}>{value.replaceAll("_", " ")}</span>;
}

export function short(id: string) {
  return id.replace(/^(e|k|drv:policy_expansion|lat:[a-z_]+):/, "");
}

export function PathChips({ ids, classes, cut }: { ids: string[]; classes?: Record<string, { confirmed?: boolean; cls?: string; temporal?: string }>; cut?: Set<string> }) {
  return (
    <span className="path">
      {ids.map((id, i) => {
        const c = classes?.[id];
        const k = c && !c.confirmed ? (c.temporal === "UNCERTAIN" ? "unc" : "lat") : "";
        return (
          <span key={id + i} className="row" style={{ gap: 4 }}>
            {i > 0 && <span className="arrow" aria-hidden="true">→</span>}
            <span className={`chip ${k} ${cut?.has(id) ? "cut" : ""}`} title={id}>
              {k === "lat" ? "◌ " : k === "unc" ? "⧗ " : ""}{short(id)}{cut?.has(id) ? " (cut)" : ""}
            </span>
          </span>
        );
      })}
    </span>
  );
}

export function Synthetic() {
  return <span className="badge b-warn" title="All data is synthetic">SYNTHETIC</span>;
}
