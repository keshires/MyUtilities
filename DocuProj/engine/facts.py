"""Parser output: per-repo structural facts (the Linker's input)."""

from __future__ import annotations

from pydantic import BaseModel

from engine.models import CodeRef, Endpoint


class OutboundCall(BaseModel):
    method: str
    target: str  # raw first-arg expression text (URL literal, template, or variable)
    code_ref: CodeRef


class ConfigUrl(BaseModel):
    key: str
    url: str
    code_ref: CodeRef


class DbAccess(BaseModel):
    engine: str  # "sqlalchemy" | "raw_sql" | "psycopg"
    detail: str  # table name or query fragment (best-effort)
    code_ref: CodeRef


class HandlerProvenance(BaseModel):
    """Outbound calls + DB accesses reachable from one endpoint's handler (transitively)."""

    outbound: list[OutboundCall] = []
    db: list[DbAccess] = []


class RepoFacts(BaseModel):
    repo: str
    language: str
    endpoints: list[Endpoint] = []
    outbound_calls: list[OutboundCall] = []
    config_urls: list[ConfigUrl] = []
    db_accesses: list[DbAccess] = []
    # endpoint id -> facts reachable from that endpoint's handler body
    handler_provenance: dict[str, HandlerProvenance] = {}
