"""Central layout: logs under ``logs/``, generated files under ``output/<category>/``.

Relative paths from CLI or from ``.env`` (when documented) resolve against the
project root so runs are consistent regardless of current working directory.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def logs_dir() -> Path:
    """``<repo>/logs`` — runtime logs only."""
    d = PROJECT_ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(*parts: str) -> Path:
    """``<repo>/output/<parts...>/`` — CSV/JSON/Excel artifacts."""
    d = PROJECT_ROOT / "output"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_project_relative(path_str: str) -> str:
    """
    For .env path values: if not absolute, treat as relative to PROJECT_ROOT.
    Empty strings are returned unchanged.
    """
    s = (path_str or "").strip()
    if not s:
        return s
    p = Path(s).expanduser()
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


def resolve_cli_artifact(
    path: Path,
    *output_subfolders: str,
) -> Path:
    """
    CLI output path: absolute paths unchanged; relative paths go under
    ``output/<subfolders>/``.
    """
    path = path.expanduser()
    if path.is_absolute():
        return path
    return output_dir(*output_subfolders) / path
