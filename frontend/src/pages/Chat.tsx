import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Route } from "../App";
import { Synthetic, useAsync } from "../components/common";

interface ChatEntity {
  id: string;
  kind: string;
  name: string;
}

interface LayaTelemetry {
  domain: string;
  confidence: number;
  urgency_level: string;
  urgency_score: number;
  is_adversarial: boolean;
  language: string;
  script: string;
  model: string;
  forward_pass_ms: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  cited_entities?: ChatEntity[];
  cypher_queries?: string[];
  provider_used?: string;
  model_used?: string;
  latency_ms?: number;
  suggested_questions?: string[];
  laya_telemetry?: LayaTelemetry;
  timestamp: string;
}

interface ProviderInfo {
  id: string;
  name: string;
  description: string;
  requires_key: boolean;
  is_active: boolean;
}

interface ProvidersResponse {
  default_provider: string;
  providers: ProviderInfo[];
  configured_model: string | null;
  configured_endpoint: string | null;
}

interface ChatApiResponse {
  reply: string;
  cited_entities: ChatEntity[];
  cypher_queries: string[];
  provider_used: string;
  model_used: string;
  latency_ms: number;
  suggested_questions: string[];
  laya_telemetry?: LayaTelemetry;
}

export function ChatPage({
  activeInv,
  go,
}: {
  activeInv?: string | null;
  go?: (route: Route, invId?: string | null, cert?: string | null) => void;
}) {
  const provAsync = useAsync(() => api.get<ProvidersResponse>("/api/v1/chat/providers"), []);
  const [provider, setProvider] = useState<string>("mock");
  const [endpoint, setEndpoint] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [showSettings, setShowSettings] = useState<boolean>(false);

  const [input, setInput] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [showCypherOnly, setShowCypherOnly] = useState<boolean>(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "m-welcome",
      role: "assistant",
      content:
        "👋 Welcome! I am **GHOSTTRACE Copilot**, your graph-native security incident assistant powered directly by **FalkorDB**.\n\n" +
        "Unlike generic LLMs that hallucinate incident response commands, **every claim I make is grounded in connected Cypher graphs, bitemporal facts, and machine-checked certificates**.\n\n" +
        "### How I can help:\n" +
        "- **Investigate Incident Root Cause**: *Why did disabling Alice's account fail to contain the attack?*\n" +
        "- **Explore Containment & Pareto Curves**: *What is the Price of Certainty for k=1 robustness?*\n" +
        "- **Examine Tampered Telemetry**: *How did Rule R2 catch the attacker's fake rotation log?*\n" +
        "- **Bitemporal Company Brain**: *Who owned `svc:payments-api` at incident time vs now?*\n" +
        "- **Direct Cypher Execution**: *MATCH (n:Entity) RETURN labels(n), count(n)*",
      suggested_questions: [
        "Why did disabling Alice fail to contain the incident?",
        "What is the Price of Certainty for k=1 robustness?",
        "Who owned payments-api at incident time vs now?",
        "MATCH (n:Entity) RETURN labels(n), count(n)",
      ],
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  useEffect(() => {
    if (provAsync.data?.default_provider) {
      setProvider(provAsync.data.default_provider);
    }
    if (provAsync.data?.configured_endpoint) {
      setEndpoint(provAsync.data.configured_endpoint);
    }
    if (provAsync.data?.configured_model) {
      setModel(provAsync.data.configured_model);
    }
  }, [provAsync.data]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  async function sendMessage(textToSend?: string) {
    const query = (textToSend ?? input).trim();
    if (!query || loading) return;

    const userMsg: Message = {
      id: `m-u-${Date.now()}`,
      role: "user",
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    // Format chat history for context
    const historyPayload = messages.slice(-6).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      const resp = await api.post<ChatApiResponse>("/api/v1/chat", {
        message: query,
        history: historyPayload,
        inv_id: activeInv ?? undefined,
        provider: provider,
        endpoint: endpoint || undefined,
        model: model || undefined,
        api_key: apiKey || undefined,
      });

      const botMsg: Message = {
        id: `m-b-${Date.now()}`,
        role: "assistant",
        content: resp.reply,
        cited_entities: resp.cited_entities,
        cypher_queries: resp.cypher_queries,
        provider_used: resp.provider_used,
        model_used: resp.model_used,
        latency_ms: resp.latency_ms,
        suggested_questions: resp.suggested_questions,
        laya_telemetry: resp.laya_telemetry,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => [...prev, botMsg]);
    } catch (err) {
      const errorMsg: Message = {
        id: `m-err-${Date.now()}`,
        role: "assistant",
        content: `❌ **Error connecting to chat engine**: ${(err as Error).message}`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="chat-page">
      {/* Top Header & Provider Controls */}
      <div className="chat-header-bar">
        <div>
          <h1 style={{ fontSize: 20, display: "flex", alignItems: "center", gap: 10 }}>
            <span>💬 Graph Copilot</span>
            <span className="badge b-accent" style={{ fontSize: 12 }}>
              FalkorDB Graph RAG
            </span>
            <span
              className="badge b-ok"
              style={{ fontSize: 12 }}
              title="Powered by NandhaKishorM/laya non-autoregressive decision engine"
            >
              ⚡ Laya System 1
            </span>
            <Synthetic />
          </h1>
          <p className="muted small" style={{ margin: "2px 0 0" }}>
            Conversational AI deeply integrated with FalkorDB Cypher, bitemporal facts, and certified containment.
          </p>
        </div>

        <div className="chat-provider-ctrl">
          <label className="small muted" htmlFor="provider-select">
            LLM Provider:
          </label>
          <select
            id="provider-select"
            className="chat-provider-select"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="mock">⚡ FalkorDB Graph Engine (Offline &amp; Fast)</option>
            <option value="openai_compatible">🌐 OpenAI / Local LLM (Ollama, vLLM)</option>
            <option value="anthropic">🧠 Anthropic Claude (3.5 Sonnet / Opus)</option>
          </select>

          <button
            className={`btn sm ${showSettings ? "primary" : ""}`}
            onClick={() => setShowSettings(!showSettings)}
            title="Configure model name, custom endpoint or API keys"
          >
            ⚙️ Settings
          </button>
        </div>
      </div>

      {/* Provider Configuration Drawer */}
      {showSettings && (
        <div className="chat-settings-card">
          <div className="row between" style={{ marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 14 }}>Provider Configuration</h3>
            <span className="badge b-neutral">Active: {provider}</span>
          </div>

          <div className="grid g3" style={{ gap: 12 }}>
            <label className="field">
              <span>Endpoint URL (OpenAI / Ollama / LocalAI)</span>
              <input
                type="text"
                placeholder="http://localhost:11434/v1 or https://api.openai.com/v1"
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
              />
            </label>

            <label className="field">
              <span>Model Name</span>
              <input
                type="text"
                placeholder="e.g. gpt-4o-mini, llama3.2, claude-3-5-sonnet-20241022"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>

            <label className="field">
              <span>API Key (Optional for local Ollama)</span>
              <input
                type="password"
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>
          </div>
          <p className="small muted" style={{ margin: "8px 0 0" }}>
            *Note: When using <b>FalkorDB Graph Engine (Default)</b>, zero API keys are required; answers are synthesized
            directly from deterministic FalkorDB Cypher traversal.*
          </p>
        </div>
      )}

      {/* Main Chat Body */}
      <div className="chat-body">
        {/* Messages Stream */}
        <div className="chat-messages" role="log" aria-live="polite">
          {messages.map((m) => (
            <div
              key={m.id}
              className={m.role === "user" ? "chat-bubble-user" : "chat-bubble-bot"}
            >
              <div
                style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontFamily: m.content.startsWith("### FalkorDB Cypher Results") ? "var(--mono)" : "inherit",
                }}
              >
                {m.content}
              </div>

              {/* Cited Graph Entities */}
              {m.cited_entities && m.cited_entities.length > 0 && (
                <div className="chat-entities-row">
                  <span className="small muted" style={{ alignSelf: "center", marginRight: 4 }}>
                    Cited Graph Entities:
                  </span>
                  {m.cited_entities.map((ent) => (
                    <span
                      key={ent.id}
                      className="chat-entity-chip"
                      title={`Inspect entity ${ent.id} in graph`}
                      onClick={() => {
                        if (go) go("investigation", activeInv);
                      }}
                    >
                      <span className="badge b-accent" style={{ fontSize: 10, padding: "0 4px" }}>
                        {ent.kind}
                      </span>
                      <span>{ent.id}</span>
                    </span>
                  ))}
                </div>
              )}

              {/* Laya System 1 Decision Telemetry */}
              {m.laya_telemetry && (
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                  <span className="badge b-accent" style={{ fontSize: 11, fontWeight: 600 }}>
                    ⚡ Laya System 1: {m.laya_telemetry.domain}
                  </span>
                  <span className="badge b-ok" style={{ fontSize: 11 }}>
                    {Math.round(m.laya_telemetry.confidence * 100)}% conf
                  </span>
                  <span className="badge b-neutral" style={{ fontSize: 11 }}>
                    {m.laya_telemetry.urgency_level} urgency
                  </span>
                  <span className="badge b-neutral" style={{ fontSize: 11 }}>
                    {m.laya_telemetry.model} ({m.laya_telemetry.language})
                  </span>
                  <span className="small muted">
                    ({m.laya_telemetry.forward_pass_ms} ms)
                  </span>
                  {m.laya_telemetry.is_adversarial && (
                    <span className="badge b-warn" style={{ fontSize: 11 }}>
                      🛡️ Guardrail: Prompt Injection Flagged
                    </span>
                  )}
                </div>
              )}

              {/* Cypher Query & Telemetry Dropdown */}
              {(m.cypher_queries?.length || m.latency_ms !== undefined) && (
                <details className="chat-telemetry-box" style={{ marginTop: 10 }}>
                  <summary className="chat-telemetry-toggle">
                    <span>⚡ Graph Telemetry &amp; Cypher</span>
                    {m.latency_ms !== undefined && (
                      <span className="badge b-ok" style={{ fontSize: 10, marginLeft: 6 }}>
                        {m.latency_ms} ms
                      </span>
                    )}
                    {m.provider_used && (
                      <span className="badge b-neutral" style={{ fontSize: 10 }}>
                        {m.provider_used}
                      </span>
                    )}
                  </summary>

                  <div style={{ marginTop: 8 }}>
                    {m.cypher_queries && m.cypher_queries.length > 0 && (
                      <div>
                        <div className="small muted" style={{ marginBottom: 4 }}>
                          FalkorDB Cypher Query Executed:
                        </div>
                        <pre style={{ margin: 0 }}>
                          <code>{m.cypher_queries.join("\n\n")}</code>
                        </pre>
                      </div>
                    )}
                    <div className="small muted" style={{ marginTop: 6 }}>
                      Engine Model: <code>{m.model_used ?? "falkordb-native"}</code>
                    </div>
                  </div>
                </details>
              )}

              {/* Follow-up Question Suggestions */}
              {m.suggested_questions && m.suggested_questions.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div className="small muted" style={{ marginBottom: 6 }}>
                    Suggested Follow-ups:
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {m.suggested_questions.map((q, idx) => (
                      <button
                        key={idx}
                        className="chat-prompt-pill"
                        onClick={() => sendMessage(q)}
                        disabled={loading}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="chat-bubble-bot">
              <span className="badge b-accent" aria-busy="true">
                Analyzing FalkorDB graph…
              </span>
              <p className="small muted" style={{ margin: "4px 0 0" }}>
                Executing Cypher queries and evaluating bitemporal facts…
              </p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Suggestion Chips */}
        <div className="chat-suggestions-bar">
          <button
            className="chat-prompt-pill"
            onClick={() => sendMessage("Why did disabling Alice fail to contain the incident?")}
          >
            ❓ Why did disabling Alice fail?
          </button>
          <button
            className="chat-prompt-pill"
            onClick={() => sendMessage("What is the Price of Certainty for k=1 robustness?")}
          >
            ⚖️ Price of Certainty (k=1)
          </button>
          <button
            className="chat-prompt-pill"
            onClick={() => sendMessage("How did Rule R2 catch the attacker's fake rotation log?")}
          >
            🛡️ Rule R2 &amp; Fake Rotation Log
          </button>
          <button
            className="chat-prompt-pill"
            onClick={() => sendMessage("Who owned payments-api at incident time vs now?")}
          >
            ❖ Company Brain: payments-api
          </button>
          <button
            className="chat-prompt-pill"
            onClick={() => {
              setInput("MATCH (n:Entity) RETURN labels(n), count(n)");
            }}
          >
            ⌘ Cypher: Entity Counts
          </button>
        </div>

        {/* Input Bar */}
        <div className="chat-input-row">
          <button
            className={`btn sm ${showCypherOnly ? "primary" : ""}`}
            onClick={() => {
              setShowCypherOnly(!showCypherOnly);
              if (!input.startsWith("MATCH")) {
                setInput("MATCH (n:Entity) RETURN n.id, labels(n) LIMIT 10");
              }
            }}
            title="Pre-populate Cypher query"
          >
            Cypher:
          </button>
          <input
            type="text"
            className="chat-input"
            placeholder="Ask about attack paths, Alice's compromise, Pareto curve, Company Brain, or write Cypher..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            className="btn primary"
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
          >
            {loading ? "Thinking…" : "Send ↵"}
          </button>
        </div>
      </div>
    </div>
  );
}
