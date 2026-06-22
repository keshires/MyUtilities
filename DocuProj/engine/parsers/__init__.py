"""Parser dispatch: source tree + language -> RepoFacts."""

from __future__ import annotations

from pathlib import Path

from engine.facts import RepoFacts
from engine.parsers._consts import build_const_map
from engine.parsers.python_fastapi import extract_fastapi_routes
from engine.parsers.python_http import extract_python_outbound
from engine.parsers.ts_angular import extract_angular_outbound


def parse(repo_path, language: str, repo: str | None = None) -> RepoFacts:
    repo = repo or Path(repo_path).name
    lang = language.lower()
    if lang == "python":
        consts = build_const_map(repo_path)  # built once, shared by both extractors
        return RepoFacts(
            repo=repo,
            language="python",
            endpoints=extract_fastapi_routes(repo_path, repo, consts),
            outbound_calls=extract_python_outbound(repo_path, repo, consts),
        )
    if lang in ("typescript", "angular", "ts", "tsx"):
        outbound, configs = extract_angular_outbound(repo_path, repo)
        return RepoFacts(
            repo=repo, language="typescript", outbound_calls=outbound, config_urls=configs
        )
    raise ValueError(f"unsupported language: {language}")


__all__ = ["parse"]
