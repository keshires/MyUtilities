"""DocuProj analysis engine."""

from engine.models import (
    AnalysisModel,
    CodeRef,
    Endpoint,
    Flow,
    FlowEdge,
    FlowNode,
    Project,
    RepoRef,
)
from engine.ingest import ResolvedRepo, ingest, load_project
from engine.facts import ConfigUrl, OutboundCall, RepoFacts
from engine.parsers import parse
from engine.linker import DeterministicResolver, LinkQuery, Resolver, link, target_path, url_path
from engine.analyze import analyze, detect_language
from engine.api import create_app

__all__ = [
    "AnalysisModel",
    "CodeRef",
    "ConfigUrl",
    "DeterministicResolver",
    "Endpoint",
    "Flow",
    "FlowEdge",
    "FlowNode",
    "LinkQuery",
    "OutboundCall",
    "Project",
    "RepoFacts",
    "RepoRef",
    "Resolver",
    "ResolvedRepo",
    "analyze",
    "create_app",
    "detect_language",
    "ingest",
    "link",
    "load_project",
    "parse",
    "target_path",
    "url_path",
]
