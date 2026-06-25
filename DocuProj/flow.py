"""One-command flow tracer. Auto-discovers the repos cloned under .workspace/edfx-flow,
traces forward provenance, and prints the flow(s) for an endpoint.

    ./.venv/Scripts/python flow.py <endpoint-substring> [--claude]

  --claude  resolve variable-URL service hops via Claude (needs ANTHROPIC_API_KEY)
"""

import sys
from pathlib import Path

from engine import ClaudeResolver, Project, RepoRef, detect_language, parse, trace_flows

WS = Path(".workspace/edfx-flow")


def main() -> int:
    use_claude = "--claude" in sys.argv
    needles = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]
    if not needles:
        print("usage: python flow.py <endpoint-substring> [--claude]")
        return 2
    needle = needles[0]
    # Git Bash (MSYS) rewrites a leading-slash arg into a Windows path; recover the tail
    if "/git/" in needle or (len(needle) > 2 and needle[1] == ":"):
        needle = needle.rsplit("/", 1)[-1]
    if not WS.exists():
        print(f"No repos cloned in {WS}. See the troubleshooting-edfx-flows skill / REPOS.md.")
        return 1

    specs = []
    for d in sorted(p for p in WS.iterdir() if p.is_dir()):
        lang = detect_language(d)
        if lang is not None:
            specs.append((d.name, lang))
    print(f"Analyzing {len(specs)} repos: {', '.join(n for n, _ in specs)} ...")
    facts = [parse(str(WS / n), lang, repo=n) for n, lang in specs]
    project = Project(id="edfx", name="EDFX",
                      repos=[RepoRef(url="x", folder=n, branch="main", sha=n) for n, _ in specs])
    model = trace_flows(facts, project, resolver=ClaudeResolver() if use_claude else None)

    matches = [fl for fl in model.flows if needle in fl.endpoint_id.lower()]
    if not matches:
        print(f"\nNo flow found for '{needle}'. The endpoint may touch no DB/downstream, "
              "or a repo on its path isn't cloned (see REPOS.md). Add --claude for variable-URL hops.")
        return 0
    for fl in matches[:8]:
        print(f"\n=== {fl.endpoint_id} ===")
        for n in fl.nodes:
            print(f"  {n.kind:9} {n.repo:26} {n.label[:34]:34} {n.code_ref.file}:{n.code_ref.line}")
        for e in fl.edges:
            print(f"  --{e.kind}({e.confidence})-> {e.from_node.split(':',1)[0]} to {e.to_node.split(':',1)[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())