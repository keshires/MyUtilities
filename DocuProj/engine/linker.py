"""Linker: join RepoFacts into a cross-repo AnalysisModel via a pluggable Resolver."""

from __future__ import annotations

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
    sources = [
        (f.repo, c.key, url_path(c.url), c.code_ref)
        for f in facts
        for c in f.config_urls
    ]
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
        seen_ui: set[str] = set()
        for repo, label, spath, ref in sources:
            confidence = resolver.score(
                LinkQuery(source_label=label, source_path=spath, source_ref=ref, endpoint=ep)
            )
            if confidence is None:
                continue
            uid = f"ui:{repo}:{label}"
            if uid not in seen_ui:
                nodes.append(FlowNode(id=uid, repo=repo, label=label, kind="ui", code_ref=ref))
                seen_ui.add(uid)
            edges.append(FlowEdge(from_node=uid, to_node=route.id, kind="http", confidence=confidence))
        if edges:
            nodes.append(route)
            flows.append(Flow(endpoint_id=ep.id, nodes=nodes, edges=edges))
    return AnalysisModel(project=project, endpoints=endpoints, flows=flows)
