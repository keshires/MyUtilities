"""Content-addressed cache for AnalysisModel, keyed by (analyzer version + repo SHAs)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from engine.models import AnalysisModel, Project
from engine.version import ANALYZER_VERSION


def cache_key(project: Project) -> str:
    parts = sorted(f"{r.folder}:{r.sha}" for r in project.repos)
    raw = "|".join([ANALYZER_VERSION, *parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class Cache:
    """Filesystem JSON cache. One file per key: <root>/<key>.json."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> AnalysisModel | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        return AnalysisModel.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, key: str, model: AnalysisModel) -> None:
        path = self.root / f"{key}.json"
        path.write_text(model.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
