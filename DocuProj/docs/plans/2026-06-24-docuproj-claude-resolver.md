# DocuProj Claude Resolver Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox steps.

**Goal:** Wire the Claude Resolver into the Linker seam to resolve the *indirected* cross-repo links deterministic matching can't — gateway outbound calls whose URL is a runtime variable, and UI calls routed through a wrapper service. Fills the §3/§10 "ambiguous links go to Claude" gap.

**Architecture:** A **batch** `ClaudeResolver` (not per-pair — one API call covers many sources × candidate endpoints, which is the only affordable shape for an LLM). It takes the outbound `OutboundCall`s + candidate `Endpoint`s, asks `claude-opus-4-8` (adaptive thinking, structured JSON output) which endpoint each call targets + a confidence, and returns links. `enrich_flows(model, facts, resolver)` adds Claude-confirmed flows to the deterministic `AnalysisModel`. The anthropic client is **injectable** so tests run with a fake (no API key, no tokens); the real client is created lazily only when no client is injected.

**Tech Stack:** Python 3.12, `anthropic` SDK (new dep), pydantic v2, pytest. Unit tests use a fake client (offline). Real validation requires `ANTHROPIC_API_KEY` and is run via a committed script, not in the test suite.

**Honest constraint:** this environment has no `ANTHROPIC_API_KEY`, so real-repo Claude validation can't run here. The code is built + unit-tested against a mock; the user runs `claude_demo.py` with their key to validate live.

## File Structure
```
DocuProj/
  requirements.txt              # + anthropic
  engine/claude_resolver.py     # ClaudeResolver (batch), ResolvedLink, prompt builder
  engine/linker.py              # + enrich_flows(model, facts, resolver)
  engine/__init__.py            # exports
  tests/test_claude_resolver.py # fake-client unit tests (offline)
  claude_demo.py                # real-run: analyze EDFX repos + Claude enrich (needs API key)
```

---

### Task 1: `ClaudeResolver` (batch, injectable, structured output)
- [ ] Add `anthropic` to `requirements.txt`; install.
- [ ] Failing test (`tests/test_claude_resolver.py`): inject a fake client returning canned JSON `{"links":[{"source_index":0,"endpoint_id":"edfx_entity_api:POST:/entity/v1/resolve","confidence":0.9}]}`; assert `ClaudeResolver(client=fake).resolve([call], [endpoint])` returns one `ResolvedLink` with that id/confidence; assert links to unknown endpoint ids are dropped; assert empty sources/endpoints → `[]` with no client call.
- [ ] Implement `engine/claude_resolver.py`: `ResolvedLink(BaseModel)`, `ClaudeResolver(client=None, model="claude-opus-4-8")`, `resolve(sources, endpoints)` → builds a prompt (numbered sources with method/target/file:line/snippet + candidate endpoints with id/method/path), calls `messages.create` with `output_config.format` JSON schema + `thinking:{type:"adaptive"}`, parses the text block, validates endpoint ids and `confidence>0`. `anthropic` imported lazily inside the default-client path only.
- [ ] Commit.

### Task 2: `enrich_flows` integration + exports
- [ ] Failing test: build a deterministic `AnalysisModel` via `link()` (a gateway outbound with a variable target → no deterministic flow), then `enrich_flows(model, facts, resolver=ClaudeResolver(client=fake))` adds a flow for the Claude-linked endpoint with an `outbound` source node and an `http` edge carrying the Claude confidence; existing flows are preserved; a link to an already-flowed endpoint adds the node/edge without duplicating.
- [ ] Implement `enrich_flows(model, facts, resolver)` in `linker.py`: collect cross-repo outbound sources + candidate endpoints, call `resolver.resolve`, merge confirmed links into `model.flows` (reuse FlowNode/FlowEdge; node id `outbound:<repo>:<idx>`). Export `ClaudeResolver`, `ResolvedLink`, `enrich_flows`.
- [ ] Full suite green; commit.

### Task 3: real-run script + validation gating
- [ ] Create `claude_demo.py`: analyze the 4 cloned EDFX repos, run `enrich_flows` with a real `ClaudeResolver()`, print added flows. Guard: if `ANTHROPIC_API_KEY` unset, print how to set it and exit 0 (no crash).
- [ ] Run `python claude_demo.py` — expected here: the no-key guard message (documents the path; real validation is the user's to run). Commit.

## Self-Review
- Batch (not per-pair) — the only affordable LLM shape; per-pair would be thousands of calls.
- Injectable client → offline unit tests, no key, no tokens spent in CI or here.
- Honest: real Claude validation deferred to the user's key via `claude_demo.py`; the suite never calls the network.
- Model `claude-opus-4-8`, adaptive thinking, structured JSON output (per claude-api skill defaults).
- Confidence from Claude flows onto the edge, so the dashboard can dash/flag low-confidence inferred links (already supported in the UI).
