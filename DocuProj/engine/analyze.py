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


def analyze(project, workspace, cache=None, languages=None, resolver=None) -> AnalysisModel:
    languages = languages or {}
    resolved = ingest(project, workspace)
    facts = []
    for repo in resolved:
        lang = languages.get(repo.folder) or detect_language(repo.path)
        if lang is None:
            continue
        facts.append(parse(repo.path, lang, repo=repo.folder))
    resolved_project = Project(
        id=project.id,
        name=project.name,
        repos=[
            RepoRef(url=r.url, folder=r.folder, branch=r.branch, sha=r.sha) for r in resolved
        ],
    )
    model = link(facts, resolved_project, resolver=resolver)
    if cache is not None:
        cache.put(cache_key(resolved_project), model)
    return model
