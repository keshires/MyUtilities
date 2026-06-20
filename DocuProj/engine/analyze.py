"""Orchestration: ingest -> detect language -> parse -> link -> cache."""

from __future__ import annotations

from pathlib import Path

from engine.cache import cache_key
from engine.ingest import ingest
from engine.linker import link
from engine.models import AnalysisModel, Project, RepoRef
from engine.parsers import parse


def detect_language(repo_path) -> str | None:
    p = Path(repo_path)
    if (p / "angular.json").exists():
        return "angular"
    if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists() or (p / "main.py").exists():
        return "python"
    if (p / "package.json").exists():
        return "typescript"
    return None
