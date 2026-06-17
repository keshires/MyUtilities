"""DocuProj analysis data model (§4 of the design spec).

All models serialize to the camelCase JSON contract the dashboard consumes.
Python attributes stay snake_case; camelCase is applied via field aliases.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    # Accept either snake_case (Python) or the camelCase alias (JSON) on input.
    model_config = ConfigDict(populate_by_name=True)


class CodeRef(_Model):
    repo: str
    file: str
    line: int
    snippet: str


class Endpoint(_Model):
    id: str
    repo: str
    method: str
    path: str
    handler_ref: CodeRef = Field(alias="handlerRef")
    language: str


class FlowNode(_Model):
    id: str
    repo: str
    label: str
    kind: Literal["ui", "route", "fn", "outbound"]
    code_ref: CodeRef = Field(alias="codeRef")


class FlowEdge(_Model):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    kind: Literal["calls", "http"]
    confidence: float = Field(ge=0.0, le=1.0)


class Flow(_Model):
    endpoint_id: str = Field(alias="endpointId")
    nodes: list[FlowNode]
    edges: list[FlowEdge]
