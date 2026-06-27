"""Demo server: analyze the cloned EDFX repos and serve a COMBINED flow model —
backward (UI -> endpoint, deterministic links) merged with forward provenance
(endpoint -> downstream service -> datastore). Serves the dashboard at /app/.
"""

import os

from engine import (
    AnalysisModel,
    ClaudeResolver,
    Flow,
    Project,
    RepoRef,
    create_app,
    link,
    parse,
    trace_flows,
)

WS = ".workspace/edfx-flow"
SPECS = [
    ("edfx-app-ui", "angular", "main"),
    ("edfx-api", "python", "master"),
    ("edfx_entity_api", "python", "main"),
    ("edfx-client-financials-api", "python", "main"),
    ("edfx-tessera-service", "python", "main"),
]


def _merge(backward: AnalysisModel, forward: AnalysisModel) -> AnalysisModel:
    """Union per-endpoint flows from the backward (UI->route) and forward (route->DB) models."""
    agg: dict[str, dict] = {}
    for fl in [*backward.flows, *forward.flows]:
        slot = agg.setdefault(fl.endpoint_id, {"nodes": {}, "edges": [], "keys": set()})
        for n in fl.nodes:
            slot["nodes"][n.id] = n
        for e in fl.edges:
            k = (e.from_node, e.to_node, e.kind)
            if k not in slot["keys"]:
                slot["keys"].add(k)
                slot["edges"].append(e)
    flows = [Flow(endpoint_id=eid, nodes=list(s["nodes"].values()), edges=s["edges"]) for eid, s in agg.items()]
    return AnalysisModel(project=backward.project, endpoints=backward.endpoints, flows=flows)


facts = []
for folder, lang, _ in SPECS:
    print(f"Parsing {folder} ({lang})...")
    facts.append(parse(f"{WS}/{folder}", lang, repo=folder))
project = Project(
    id="edfx-flow", name="EDFX Flow",
    repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f, _, b in SPECS],
)
# Resolve runtime-variable gateway->service hops with Claude when a key is present;
# otherwise the deterministic forward trace runs offline (variable-URL edges stay unlinked).
resolver = ClaudeResolver() if os.environ.get("ANTHROPIC_API_KEY") else None
print(f"Forward trace: {'Claude resolver (ANTHROPIC_API_KEY set)' if resolver else 'deterministic only'}")
model = _merge(link(facts, project), trace_flows(facts, project, resolver=resolver))
ds = sum(1 for fl in model.flows for n in fl.nodes if n.kind == "datastore")
print(f"Combined: {len(model.endpoints)} endpoints, {len(model.flows)} flows, {ds} datastore nodes. Dashboard at /app/")
app = create_app(projects_dir="projects", workspace=".workspace", store={"edfx-flow": model})