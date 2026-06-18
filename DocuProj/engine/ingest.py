"""Ingestor: clone/fetch repos from a project.json, resolve branch + HEAD SHA."""

from __future__ import annotations

import json
from pathlib import Path

from engine.models import Project, RepoRef


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    name = data["project"]
    repos = [RepoRef.model_validate(r) for r in data["repos"]]
    return Project(id=name, name=name, repos=repos)
