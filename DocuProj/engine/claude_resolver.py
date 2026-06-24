"""Claude-backed Resolver for indirected cross-repo links (spec §3 hybrid linking).

Batch design: one Anthropic API call scores many outbound calls against many
candidate endpoints — the only affordable shape for an LLM (per-pair would be
thousands of calls). The client is injectable so tests run offline with a fake;
the real `anthropic` client is created lazily only when no client is injected.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from engine.facts import OutboundCall
from engine.models import Endpoint

DEFAULT_MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_index": {"type": "integer"},
                    "endpoint_id": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["source_index", "endpoint_id", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["links"],
    "additionalProperties": False,
}


class ResolvedLink(BaseModel):
    source_index: int
    endpoint_id: str
    confidence: float


def _build_prompt(sources: list[OutboundCall], endpoints: list[Endpoint]) -> str:
    src_lines = [
        f"[{i}] {s.method} target={s.target!r} at {s.code_ref.repo}/{s.code_ref.file}:{s.code_ref.line}"
        f"  | {s.code_ref.snippet}"
        for i, s in enumerate(sources)
    ]
    ep_lines = [f"{e.id}  ({e.method} {e.path}  in {e.repo})" for e in endpoints]
    return (
        "You are mapping outbound HTTP calls in one repository to the inbound API "
        "endpoints they invoke in OTHER repositories. For each outbound call, pick the "
        "single most likely endpoint it targets, or omit it if none is a plausible match.\n\n"
        "OUTBOUND CALLS (by index):\n" + "\n".join(src_lines) + "\n\n"
        "CANDIDATE ENDPOINTS (use the exact id):\n" + "\n".join(ep_lines) + "\n\n"
        "Return JSON {\"links\": [{\"source_index\", \"endpoint_id\", \"confidence\"}]}. "
        "confidence is 0.0-1.0 (your certainty the call hits that endpoint). "
        "Only include links you have real evidence for; omit guesses."
    )


class ClaudeResolver:
    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        self._client = client
        self.model = model

    def _default_client(self):
        import anthropic  # lazy: keeps the SDK optional for the offline test suite

        return anthropic.Anthropic()

    def _call_model(self, prompt: str) -> str:
        client = self._client or self._default_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        return next(b.text for b in resp.content if b.type == "text")

    def resolve(self, sources: list[OutboundCall], endpoints: list[Endpoint]) -> list[ResolvedLink]:
        if not sources or not endpoints:
            return []
        data = json.loads(self._call_model(_build_prompt(sources, endpoints)))
        valid = {e.id for e in endpoints}
        links: list[ResolvedLink] = []
        for raw in data.get("links", []):
            eid = raw.get("endpoint_id")
            conf = float(raw.get("confidence", 0))
            if eid in valid and conf > 0:
                links.append(ResolvedLink(source_index=int(raw["source_index"]), endpoint_id=eid, confidence=conf))
        return links