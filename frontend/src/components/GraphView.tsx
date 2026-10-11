import cytoscape from "cytoscape";
import type { Core, ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import type { GEdge, GraphData } from "../types";

const SHAPES: Record<string, string> = {
  Identity: "ellipse", Credential: "diamond", Host: "round-rectangle", Service: "round-hexagon", Asset: "barrel",
  Repository: "round-tag", Team: "round-pentagon", Person: "ellipse", Policy: "round-triangle", Group: "octagon",
};

function css(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function edgeLabel(e: GEdge) {
  const cls = e.temporal === "INACTIVE" ? "INACTIVE" : e.temporal === "UNCERTAIN" ? "UNKNOWN-VALIDITY" : e.cls === "OBSERVED" ? "OBS" : e.cls === "DERIVED" ? "DER" : "LAT";
  const f = (e.flags ?? []).map((x) => ({ disputed: "⚠", possible_false_flag: "⚑", weakly_supported: "◔", stale: "⏳" } as Record<string, string>)[x] ?? "").join("");
  return `${e.type} · ${cls}${f ? " " + f : ""}`;
}

export function GraphView({ data, highlight, removed, onSelectEdge, onSelectNode, showLabels = false, onToggleLabels }: {
  data: GraphData; highlight?: Set<string>; removed?: Set<string>; onToggleLabels?: () => void;
  onSelectEdge?: (e: GEdge) => void; onSelectNode?: (id: string) => void; showLabels?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const all = useMemo(() => [...data.edges, ...data.inactive_edges], [data]);

  useEffect(() => {
    if (!ref.current) return;
    const els: ElementDefinition[] = [
      ...data.nodes.map((n) => ({
        data: { id: n.id, label: `${n.is_source ? "⚠ " : n.is_target ? "◎ " : ""}${n.name}`, kind: n.label },
        classes: [n.is_source ? "source" : "", n.is_target ? "target" : ""].join(" "),
      })),
      ...all.map((e) => ({
        data: { id: `${e.edge_id}#${e.version}`, eid: e.edge_id, source: e.src, target: e.dst, label: edgeLabel(e) },
        classes: [
          e.temporal === "INACTIVE" ? "inactive" : e.temporal === "UNCERTAIN" ? "uncertain" : (e.cls ?? "").toLowerCase(),
          (e.flags ?? []).includes("disputed") ? "disputed" : "", (e.flags ?? []).includes("possible_false_flag") ? "ff" : "",
          highlight?.has(e.edge_id) ? "hl" : "", removed?.has(e.edge_id) ? "cut" : "",
        ].join(" "),
      })),
    ];
    const ink = css("--ink"), ink2 = css("--ink-2"), line = css("--line"), latent = css("--latent"), derived = css("--derived");
    const bad = css("--bad"), accent = css("--accent"), panel = css("--panel"), warn = css("--warn"), ok = css("--ok");
    const inst = cytoscape({
      container: ref.current,
      elements: els,
      wheelSensitivity: 0.25,
      style: [
        { selector: "node", style: { label: "data(label)", "font-size": 10, color: ink, "text-valign": "bottom", "text-margin-y": 4,
          "background-color": panel, "border-width": 2, "border-color": ink2, width: 26, height: 26, "text-wrap": "wrap", "text-max-width": "110px",
          shape: (el: any) => (SHAPES[el.data("kind")] ?? "ellipse") as any } as any },
        { selector: "node.source", style: { "border-color": bad, "border-width": 4 } },
        { selector: "node.target", style: { "border-color": accent, "border-width": 4, "background-color": accent } },
        { selector: "edge", style: { width: 2, "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": ink2,
          "target-arrow-color": ink2, label: showLabels ? "data(label)" : "", "font-size": 8, color: ink2, "text-rotation": "autorotate",
          "text-background-color": panel, "text-background-opacity": 0.85, "text-background-padding": "1px" } as any },
        { selector: "edge:selected, edge.hl", style: { label: "data(label)" } },
        { selector: "edge.observed", style: { "line-color": ok, "target-arrow-color": ok } },
        { selector: "edge.derived", style: { "line-style": "dotted", "line-color": derived, "target-arrow-color": derived, width: 3 } },
        { selector: "edge.latent", style: { "line-style": "dashed", "line-color": latent, "target-arrow-color": latent } },
        { selector: "edge.uncertain", style: { "line-style": "dashed", "line-dash-pattern": [2, 4], "line-color": warn, "target-arrow-color": warn } },
        { selector: "edge.inactive", style: { "line-style": "dotted", "line-color": line, "target-arrow-color": line, opacity: 0.8 } },
        { selector: "edge.disputed", style: { "line-color": warn, "target-arrow-color": warn, width: 3 } },
        { selector: "edge.ff", style: { "line-color": bad, "target-arrow-color": bad } },
        { selector: "edge.hl", style: { width: 5, "z-index": 10 } },
        { selector: "edge.cut", style: { opacity: 0.35, "line-style": "dotted", "target-arrow-shape": "tee" } },
        { selector: ":selected", style: { "overlay-color": accent, "overlay-opacity": 0.18, "overlay-padding": 6 } as any },
      ],
      layout: { name: "breadthfirst", directed: true, roots: data.nodes.filter((n) => n.is_source).map((n) => `[id = "${n.id}"]`).join(","),
        spacingFactor: 1.75, padding: 30, animate: false, avoidOverlap: true, nodeDimensionsIncludeLabels: true } as any,
    });
    inst.on("tap", "edge", (ev) => {
      const id = ev.target.data("eid");
      const v = Number(String(ev.target.id()).split("#").pop());
      const e = all.find((x) => x.edge_id === id && x.version === v);
      if (e && onSelectEdge) onSelectEdge(e);
    });
    inst.on("tap", "node", (ev) => onSelectNode?.(ev.target.id()));
    cy.current = inst;
    return () => inst.destroy();
  }, [data, all, highlight, removed, onSelectEdge, onSelectNode, showLabels]);

  return (
    <div className="graph" role="img" aria-label={`Attack graph with ${data.nodes.length} nodes and ${all.length} edges; use the table view for a text listing`}>
      <div className="graph-tools">
        {onToggleLabels && <button className="btn sm" aria-pressed={showLabels} onClick={onToggleLabels}>Edge labels</button>}
        <button className="btn sm" onClick={() => cy.current?.fit(undefined, 24)} aria-label="Fit graph to view">Fit</button>
        <button className="btn sm" onClick={() => cy.current?.zoom((cy.current?.zoom() ?? 1) * 1.25)} aria-label="Zoom in">＋</button>
        <button className="btn sm" onClick={() => cy.current?.zoom((cy.current?.zoom() ?? 1) / 1.25)} aria-label="Zoom out">－</button>
      </div>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
    </div>
  );
}

export function Legend() {
  return (
    <div className="legend" aria-label="Graph legend">
      <span><i className="swatch" style={{ borderColor: "var(--ok)" }} /> ● OBSERVED (OBS)</span>
      <span><i className="swatch der" /> ◆ DERIVED (DER)</span>
      <span><i className="swatch lat" /> ◌ LATENT (LAT, unverified)</span>
      <span><i className="swatch inact" /> ○ inactive at T</span>
      <span>⚠ disputed removal</span><span>⚑ possible false flag</span><span>◔ weakly supported</span>
      <span>⚠ red ring = suspected-compromised source</span><span>◎ filled = target</span>
    </div>
  );
}
