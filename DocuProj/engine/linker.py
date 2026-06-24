"""Linker: join RepoFacts into a cross-repo AnalysisModel via a pluggable Resolver."""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel

from engine.facts import RepoFacts
from engine.models import AnalysisModel, CodeRef, Endpoint, Flow, FlowEdge, FlowNode, Project


def url_path(url: str) -> str:
    """Path component of a config URL. Absolute -> its path; relative -> unchanged."""
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return parts.path
    return url


_PATH_LITERAL = re.compile(r"""['"`](/[^'"`]*)['"`]""")


def target_path(target: str) -> str:
    """Extract a path from an outbound target: a quoted '/…' literal, or a bare resolved '/…'."""
    m = _PATH_LITERAL.search(target)
    if m:
        return m.group(1)
    if target.startswith("/"):
        return target  # already a resolved bare path
    return ""


class LinkQuery(BaseModel):
    """A candidate link a Resolver scores: a UI source against one inbound endpoint."""

    source_label: str          # e.g. the endPointConfig key
    source_path: str           # URL path of the source ("" if unknown)
    source_ref: CodeRef        # where the source lives (snippet for a Claude resolver)
    endpoint: Endpoint


class Resolver(Protocol):
    def score(self, query: LinkQuery) -> float | None:
        """Confidence 0..1 that the source links to the endpoint, or None for no link."""
        ...


class DeterministicResolver:
    """Path matching: exact path == 1.0, service-prefix == 0.5, else no link."""

    def score(self, query: LinkQuery) -> float | None:
        source = query.source_path.rstrip("/")
        if not source:
            return None
        endpoint_path = query.endpoint.path
        if endpoint_path == query.source_path or endpoint_path == source:
            return 1.0
        if endpoint_path.startswith(source + "/"):
            return 0.5
        return None


def link(
    facts: list[RepoFacts],
    project: Project,
    resolver: Resolver | None = None,
) -> AnalysisModel:
    resolver = resolver or DeterministicResolver()
    endpoints = [ep for f in facts for ep in f.endpoints]

    # Sources: UI config URLs (kind "ui") + outbound HTTP calls (kind "outbound").
    sources = []
    for f in facts:
        for c in f.config_urls:
            sources.append((f.repo, "ui", c.key, url_path(c.url), c.code_ref))
        for o in f.outbound_calls:
            sources.append(
                (f.repo, "outbound", f"{o.method} {o.target}"[:48], target_path(o.target), o.code_ref)
            )

    flows: list[Flow] = []
    for ep in endpoints:
        route = FlowNode(
            id=f"route:{ep.id}",
            repo=ep.repo,
            label=f"{ep.method} {ep.path}",
            kind="route",
            code_ref=ep.handler_ref,
        )
        nodes: list[FlowNode] = []
        edges: list[FlowEdge] = []
        seen: set[str] = set()
        for src_repo, kind, label, spath, ref in sources:
            if src_repo == ep.repo:
                continue  # cross-repo links only
            confidence = resolver.score(
                LinkQuery(source_label=label, source_path=spath, source_ref=ref, endpoint=ep)
            )
            if confidence is None:
                continue
            nid = f"{kind}:{src_repo}:{label}"
            if nid not in seen:
                nodes.append(FlowNode(id=nid, repo=src_repo, label=label, kind=kind, code_ref=ref))
                seen.add(nid)
            edges.append(FlowEdge(from_node=nid, to_node=route.id, kind="http", confidence=confidence))
        if edges:
            nodes.append(route)
            flows.append(Flow(endpoint_id=ep.id, nodes=nodes, edges=edges))
    return AnalysisModel(project=project, endpoints=endpoints, flows=flows)


def enrich_flows(model: AnalysisModel, facts, resolver) -> AnalysisModel:
    """Augment a deterministic AnalysisModel with Claude-resolved cross-repo links.

    `resolver.resolve(sources, endpoints)` returns ResolvedLink(source_index, endpoint_id,
    confidence). Each confirmed link adds an `outbound` source node + `http` edge to the
    target endpoint's flow (creating the flow if the deterministic pass produced none).
    """
    sources = [(f.repo, o) for f in facts for o in f.outbound_calls]
    endpoints_by_id = {ep.id: ep for ep in model.endpoints}
    candidates = list(model.endpoints)
    links = resolver.resolve([o for _repo, o in sources], candidates)

    flows_by_endpoint = {f.endpoint_id: f for f in model.flows}
    for link_ in links:
        if link_.source_index >= len(sources):
            continue
        src_repo, call = sources[link_.source_index]
        ep = endpoints_by_id.get(link_.endpoint_id)
        if ep is None or src_repo == ep.repo:
            continue  # cross-repo links only
        nid = f"outbound:{src_repo}:{link_.source_index}"
        flow = flows_by_endpoint.get(ep.id)
        if flow is None:
            route = FlowNode(
                id=f"route:{ep.id}", repo=ep.repo, label=f"{ep.method} {ep.path}",
                kind="route", code_ref=ep.handler_ref,
            )
            flow = Flow(endpoint_id=ep.id, nodes=[route], edges=[])
            flows_by_endpoint[ep.id] = flow
            model.flows.append(flow)
        route_id = f"route:{ep.id}"
        if not any(n.id == nid for n in flow.nodes):
            flow.nodes.insert(
                0, FlowNode(id=nid, repo=src_repo, label=f"{call.method} {call.target}"[:48],
                            kind="outbound", code_ref=call.code_ref)
            )
        if not any(e.from_node == nid and e.to_node == route_id for e in flow.edges):
            flow.edges.append(FlowEdge(from_node=nid, to_node=route_id, kind="http", confidence=link_.confidence))
    return model
