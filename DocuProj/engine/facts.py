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


class RepoFacts(BaseModel):
    repo: str
    language: str
    endpoints: list[Endpoint] = []
    outbound_calls: list[OutboundCall] = []
    config_urls: list[ConfigUrl] = []
