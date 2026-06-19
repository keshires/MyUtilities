"""Ingestor: clone/fetch repos from a project.json, resolve branch + HEAD SHA."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel

from engine.models import Project, RepoRef


class ResolvedRepo(BaseModel):
    """One repo resolved to a local checkout at a pinned SHA."""

    url: str
    folder: str
    branch: str
    sha: str
    path: str


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    name = data["project"]
    repos = [RepoRef.model_validate(r) for r in data["repos"]]
    return Project(id=name, name=name, repos=repos)


def run_git(args: list[str], cwd: str | Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def head_sha(repo_path: str | Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_path)


def clone_or_update(url: str, dest: str | Path, branch: str) -> None:
    dest = Path(dest)
    if (dest / ".git").exists():
        run_git(["fetch", "--prune", "origin"], cwd=dest)
        run_git(["checkout", branch], cwd=dest)
        run_git(["reset", "--hard", f"origin/{branch}"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_git(["clone", "--branch", branch, url, str(dest)])


def ingest(
    project: Project,
    workspace_root: str | Path,
    branch_overrides: dict[str, str] | None = None,
) -> list[ResolvedRepo]:
    overrides = branch_overrides or {}
    workspace_root = Path(workspace_root)
    resolved: list[ResolvedRepo] = []
    for repo in project.repos:
        branch = overrides.get(repo.folder, repo.branch)
        dest = workspace_root / project.id / repo.folder
        clone_or_update(repo.url, dest, branch)
        resolved.append(
            ResolvedRepo(
                url=repo.url,
                folder=repo.folder,
                branch=branch,
                sha=head_sha(dest),
                path=str(dest),
            )
        )
    return resolved
