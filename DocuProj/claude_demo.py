"""Live Claude-resolver demo: analyze the cloned EDFX repos, then ask Claude to
resolve the indirected cross-repo links the deterministic linker can't.

Requires ANTHROPIC_API_KEY (real API calls, spends tokens). Run from DocuProj/:
    ./.venv/Scripts/python claude_demo.py
"""

import os
import sys

from engine import ClaudeResolver, Project, RepoRef, enrich_flows, link, parse

WS = ".workspace/edfx-flow"
SPECS = [
    ("edfx-app-ui", "angular", "main"),
    ("edfx-api", "python", "master"),
    ("edfx_entity_api", "python", "main"),
    ("edfx-client-financials-api", "python", "main"),
]


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set - skipping the live Claude run.\n"
            "Set it and re-run to resolve indirected links:\n"
            '    $env:ANTHROPIC_API_KEY = "sk-ant-..."   # PowerShell\n'
            "    ./.venv/Scripts/python claude_demo.py"
        )
        return 0

    facts = [parse(f"{WS}/{f}", lang, repo=f) for f, lang, _ in SPECS]
    project = Project(
        id="edfx-flow", name="EDFX Flow",
        repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f, _, b in SPECS],
    )
    model = link(facts, project)
    before = len(model.flows)
    print(f"deterministic: {len(model.endpoints)} endpoints, {before} flows")

    model = enrich_flows(model, facts, ClaudeResolver())
    added = len(model.flows) - before
    print(f"after Claude enrichment: {len(model.flows)} flows (+{added})")

    # show a few Claude-added flows (those with an `outbound` source node)
    shown = 0
    for fl in model.flows:
        outs = [n for n in fl.nodes if n.kind == "outbound"]
        if not outs:
            continue
        route = next(n for n in fl.nodes if n.kind == "route")
        conf = max(e.confidence for e in fl.edges)
        print(f"   {route.label[:44]:44} <= {outs[0].label[:32]}  conf={conf}")
        shown += 1
        if shown >= 8:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())