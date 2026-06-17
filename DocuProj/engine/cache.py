"""Content-addressed cache for AnalysisModel, keyed by (analyzer version + repo SHAs)."""

from __future__ import annotations

import hashlib

from engine.models import Project
from engine.version import ANALYZER_VERSION


def cache_key(project: Project) -> str:
    parts = sorted(f"{r.folder}:{r.sha}" for r in project.repos)
    raw = "|".join([ANALYZER_VERSION, *parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
