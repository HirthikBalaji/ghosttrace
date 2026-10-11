"""Claude provider (official `anthropic` SDK).

The model only proposes, summarises and explains. Its output is constrained to a strict JSON schema derived
from the agent's Pydantic output model (`output_config.format`), validated again with Pydantic, and every id
it cites is checked against graph results by the caller. Evidence text is passed only inside delimited
UNTRUSTED_DATA blocks. A refusal or malformed response is a handled `LLMError`, never a fabricated answer.

Configure with `GT_LLM_PROVIDER=anthropic` and credentials the SDK resolves itself (`ANTHROPIC_API_KEY`, or an
`ant auth login` profile). Model: `GT_LLM_MODEL` (default `claude-opus-5-5`).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam
from pydantic import BaseModel, ValidationError

from app.agents.llm import SYSTEM_PROMPT, LLMError, Provider, Usage

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema -> structured-outputs schema: every object closed, every property required."""
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node: Any) -> None:
        """Visit a schema node. Keys of a `properties` / `$defs` map are names, not keywords: never strip them."""
        if isinstance(node, list):
            for v in node:
                fix(v)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        node.pop("title", None)
        if node.get("type") == "object" or "properties" in node:
            props = node.setdefault("properties", {})
            node["required"] = list(props)
            if node.get("additionalProperties", True) is True:
                node["additionalProperties"] = False
        for key, value in node.items():
            if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
                for sub in value.values():
                    fix(sub)
            else:
                fix(value)

    fix(schema)
    return schema


TASK_INSTRUCTIONS = {
    "investigation_summary": "Summarise the investigation for an incident responder in 3-5 sentences. Cite hypothesis ids.",
    "plan_explanation": "Explain the Price-of-Certainty points: what each robustness level buys and costs. Cite action ids.",
    "red_team_nominations": (
        "You are the red team. From the candidate (template_id, src, dst) list, nominate the instantiations most likely to "
        "reopen a containment plan. Use only candidates from the list; they will be checked against graph preconditions."
    ),
    "propose_containment": (
        "Propose up to 3 containment plans using ONLY action ids from `candidate_actions`. Each plan must aim to cut every "
        "confirmed attack path while keeping hard flows working. Every plan will be simulated and certified by a "
        "deterministic checker; an incorrect plan will be rejected and shown as rejected."
    ),
    "llm_only_recommendation": "Recommend containment actions from the alert text.",
}


class ClaudeProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str | None = None, client: anthropic.Anthropic | None = None, effort: str = "low"):
        self.model = model or DEFAULT_MODEL
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=120.0)
        self.effort = effort

    def complete(
        self, task: str, structured: dict[str, Any], untrusted: list[str], schema: type[BaseModel], max_tokens: int = 16000
    ) -> tuple[BaseModel, Usage]:
        instruction = TASK_INSTRUCTIONS.get(task, "Complete the task described by the structured input.")
        user = (
            f"TASK: {task}\n{instruction}\n\n"
            f"STRUCTURED_INPUT (trusted; produced by deterministic graph queries):\n"
            f"{json.dumps(structured, default=str, sort_keys=True)[:60000]}\n\n" + "\n".join(untrusted)
        )
        output_config: BetaOutputConfigParam = {
            "effort": self.effort,  # type: ignore[typeddict-item]
            "format": {"type": "json_schema", "schema": strict_schema(schema)},
        }
        messages: list[BetaMessageParam] = [{"role": "user", "content": user}]
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max(1024, max_tokens),
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=SYSTEM_PROMPT,
                output_config=output_config,
                messages=messages,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("anthropic: authentication failed (check ANTHROPIC_API_KEY / ant auth login)") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("anthropic: rate limited") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"anthropic: bad request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"anthropic: API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("anthropic: connection error") from exc
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise LLMError(f"anthropic: model declined (category={cat})")
        if resp.stop_reason == "max_tokens":
            raise LLMError("anthropic: output truncated at max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("anthropic: no text block in response")
        try:
            out = schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError(f"anthropic: malformed structured output: {type(exc).__name__}") from exc
        u = resp.usage
        return out, Usage(int(u.input_tokens or 0), int(u.output_tokens or 0), True)
