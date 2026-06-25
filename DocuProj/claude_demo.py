"""Live Claude-resolver demo for forward provenance: analyze the cloned EDFX repos,
then trace each endpoint forward (handler -> downstream service -> datastore), using
Claude to resolve the variable-URL gateway->service calls deterministic matching can't.

Requires ANTHROPIC_API_KEY (real API calls, spends tokens). Run from DocuProj/:
    ./.venv/Scripts/python claude_demo.py
"""

import os
import sys

from engine import ClaudeResolver, Project, RepoRef, parse, trace_flows

WS = ".workspace/edfx-flow"
SPECS = [
    ("edfx-app-ui", "angular", "main"),
    ("edfx-api", "python", "master"),
    ("edfx_entity_api", "python", "main"),
    ("edfx-client-financials-api", "python", "main"),
    ("edfx-tessera-service", "python", "main"),
]


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set - skipping the live Claude run.\n"
            "Set it and re-run to resolve gateway->service edges:\n"
            '    $env:ANTHROPIC_API_KEY = "sk-ant-..."   # PowerShell\n'
            "    ./.venv/Scripts/python claude_demo.py"
        )
        return 0

    facts = [parse(f"{WS}/{f}", lang, repo=f) for f, lang, _ in SPECS]
    project = Project(
        id="edfx-flow", name="EDFX Flow",
        repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f, _, b in SPECS],
    )

    det = trace_flows(facts, project)
    full = trace_flows(facts, project, resolver=ClaudeResolver())

    def multi_repo(model):
        return [fl for fl in model.flows if len({n.repo for n in fl.nodes}) >= 3]

    print(f"forward flows: deterministic={len(det.flows)}, with-Claude={len(full.flows)}")
    print(f"multi-repo chains (>=3 repos): deterministic={len(multi_repo(det))}, with-Claude={len(multi_repo(full))}\n")

    shown = 0
    for fl in full.flows:
        repos = {n.repo for n in fl.nodes}
        has_ds = any(n.kind == "datastore" for n in fl.nodes)
        if len(repos) >= 3 and has_ds:
            chain = " -> ".join(n.label[:24] for n in fl.nodes)
            print(f"   {fl.endpoint_id[-40:]}:\n      {chain}")
            shown += 1
            if shown >= 6:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())