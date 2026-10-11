export interface Investigation {
  id: string;
  title: string;
  status: string;
  incident_id: string;
  scenario_id: string;
  created_at: number;
  T_incident: number;
  T_analysis: number;
  tau_analysis: number;
  K: number;
  policy: string;
  clock?: string;
  error?: string;
}

export interface Task {
  task_id: string;
  agent_type: string;
  seq: number;
  status: string;
  attempt_count: number;
  error_category?: string;
  error?: string;
  started_at?: number;
  finished_at?: number;
  tool_calls?: number;
  lease_owner?: string;
}

export interface Handoff {
  from_task: string;
  from_agent: string;
  to_task: string;
  to_agent: string;
  at: number;
  refs: string[];
  note: string;
}

export interface GEdge {
  edge_id: string;
  version: number;
  type: string;
  src: string;
  dst: string;
  cls?: "OBSERVED" | "DERIVED" | "LATENT";
  temporal: "ACTIVE" | "UNCERTAIN" | "INACTIVE";
  flags?: string[];
  template_id?: string | null;
  verify_cost?: number;
  source_ids?: string[];
  dispute_source_ids?: string[];
  confirmed?: boolean;
  kind?: string | null;
  rule_id?: string | null;
  parent_ids?: string[];
  note?: string;
  valid_from?: string | null;
  valid_to?: string | null;
  valid_open_ended?: boolean | null;
  tx_from?: string | null;
  tx_to?: string | null;
  valid_to_source_ids?: string[];
}

export interface GNode {
  id: string;
  label: string;
  name: string;
  is_source: boolean;
  is_target: boolean;
  segment?: string | null;
}

export interface GraphData {
  nodes: GNode[];
  edges: GEdge[];
  inactive_edges: GEdge[];
  T: string;
  tau: string;
  T_ms: number;
  tau_ms: number;
  policy: string;
  bounds: { T_incident: number; now: number };
}

export interface ParetoPoint {
  k: number;
  feasible: boolean;
  total_cost: number | null;
  actions: string[];
  reopening_distance: number | null;
  pareto_optimal: boolean;
  optimality: string;
  infeasible_reason: string | null;
}

export interface Action {
  id: string;
  type: string;
  target_id: string;
  target_type?: string;
  cost: number;
  cost_basis: string;
  reversibility: string;
  removes: string[];
  supporting_evidence_ids: string[];
  mode: string;
}

export interface Certificate {
  certificate_id: string;
  schema_version: string;
  status: "contained" | "not_contained";
  world_time_T: number;
  knowledge_time_tau: number;
  snapshot_hash: string;
  trust_policy: string;
  sources: string[];
  targets: string[];
  actions: Action[];
  residual_confirmed_paths: string[][];
  robustness: {
    k_target: number;
    k_certified: number;
    min_reopening_latent_edges: number | null;
    witness_paths: string[][];
    verification_priority: { edge_id: string; template: string; verify_cost: number }[];
  };
  flows: { flow_id: string; kind: string; u: string; v: string; weight: number; preserved: boolean }[];
  cost: { operational: number; soft_flow_penalty: number; total: number };
  optimality: { status: string; gap: number | null; search_space: string; lower_bound: number | null; candidate_count: number };
  disputed_removals: string[];
  requires_human_scrutiny: { action_id: string; reason: string; false_flag_edges: string[] }[];
  load_bearing_evidence: string[][];
  load_bearing_detail?: { sources: string[]; invalidates: string }[];
  assumptions: string[];
  limitations: string[];
  statement: string;
  mode: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  kind: string;
  target_ids: string[];
  pivot_id?: string | null;
  path_class: string | null;
  paths: { edge_ids: string[]; node_ids: string[]; path_class: string; latent_count: number; uncertain_count: number; assumptions: string[]; edge_classes: string[] }[];
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  assumptions: string[];
  unknowns: string[];
  known_at_incident_time?: boolean | null;
}

export interface Verdict {
  hypothesis_id: string;
  status: string;
  reasons: string[];
  citations_resolved: number;
  citations_total: number;
  independent_roots: number;
  temporal_check: string;
  flags: string[];
}

export interface Source {
  source_id: string;
  system: string;
  integrity: string;
  attacker_influenceable: boolean;
  root_id: string;
  trust_class: string;
  observed_at_iso: string;
  ingested_at_iso: string;
  content: string;
  contains_instructions: boolean;
  derived_from: string[];
  incident_evidence: boolean;
}

export interface Memory {
  memory_id: string;
  category: string;
  content: string;
  source_ids: string[];
  scope: string;
  investigation_id: string;
  taint: boolean;
  taint_reasons: string[];
  status: string;
  created_at: number;
  expires_at: number;
  created_by: string;
  promoted_from?: string;
}

export interface BrainAnswer {
  question: string;
  subject_id: string;
  answer: string;
  primary: Record<string, any>[];
  supporting_edge_ids: string[];
  source_ids: string[];
  temporal_scope: { T: number; tau: number; T_iso: string; tau_iso: string; meaning: string };
  warnings: string[];
  contradictions: Record<string, any>[];
  unknowns: string[];
  paths: string[][];
}
