"""DocuProj analysis data model (§4 of the design spec).

All models serialize to the camelCase JSON contract the dashboard consumes.
Python attributes stay snake_case; camelCase is applied via field aliases.
"""

from __future__ import annotations

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
