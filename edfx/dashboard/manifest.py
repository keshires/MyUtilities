"""Load and validate the utilities catalog manifest (utilities.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
import project_paths

MANIFEST_PATH = project_paths.PROJECT_ROOT / "utilities.yaml"


class ManifestError(Exception):
    """Raised when the manifest is missing or fails validation."""


class Arg(BaseModel):
    flag: str
    type: str = "str"
    choices: list[str] | None = None
    default: object | None = None
    required: bool = False
    help: str = ""


class Outputs(BaseModel):
    logs_glob: str | None = None
    output_glob: str | None = None
    summary_suffix: str | None = None


class Utility(BaseModel):
    id: str
    name: str
    script: str
    category: str
    purpose: str
    invocation: str  # "cli" | "env-config"
    args: list[Arg] = []
    env_required: list[str] = []
    outputs: Outputs = Outputs()
    docs: list[str] = []
    safety: str = ""


class Category(BaseModel):
    id: str
    name: str


class Manifest(BaseModel):
    categories: list[Category]
    utilities: list[Utility]


def load_manifest(path: Path | None = None) -> Manifest:
    p = path or MANIFEST_PATH
    if not p.exists():
        raise ManifestError(f"Manifest not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"Manifest YAML parse error: {exc}") from exc
    try:
        model = Manifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"Manifest validation error: {exc}") from exc
    known = {c.id for c in model.categories}
    bad = [u.id for u in model.utilities if u.category not in known]
    if bad:
        raise ManifestError(f"Utilities reference unknown categories: {bad}")
    return model
