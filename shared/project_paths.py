"""Shared path utilities — caller-aware project root for edfx/, credit-edge/, and riskcalc/.

PROJECT_ROOT resolves to the app folder (<app>/) by walking the call stack to find
the first non-internal caller. All consuming scripts live at <app>/<subfolder>/,
so caller.parent.parent == <app>/.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path


def _find_app_root() -> Path:
    for frame_info in inspect.stack():
        filename = frame_info.filename
        # Skip synthetic/frozen frames (e.g. <frozen importlib._bootstrap>)
        if filename.startswith("<"):
            continue
        p = Path(filename).resolve()
        # Skip project_paths.py itself
        if p.name == "project_paths.py":
            continue
        # Skip venv frames
        if str(p).startswith(sys.prefix):
            continue
        # Skip Python stdlib (base Python installation)
        if str(p).startswith(sys.base_prefix):
            continue
        return p.parent.parent
    return Path.cwd()


PROJECT_ROOT = _find_app_root()


def logs_dir(*parts: str) -> Path:
    """``<app>/logs/<parts...>/`` — runtime logs."""
    d = PROJECT_ROOT / "logs"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(*parts: str) -> Path:
    """``<app>/output/<parts...>/`` — CSV/JSON/Excel artifacts."""
    d = PROJECT_ROOT / "output"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def input_dir(*parts: str) -> Path:
    """``<app>/input/<parts...>/`` — input files a utility reads."""
    d = PROJECT_ROOT / "input"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_project_relative(path_str: str) -> str:
    """For .env path values: if not absolute, treat as relative to PROJECT_ROOT."""
    s = (path_str or "").strip()
    if not s:
        return s
    p = Path(s).expanduser()
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


def resolve_cli_artifact(path: Path, *output_subfolders: str) -> Path:
    """CLI output path: absolute unchanged; relative → output/<subfolders>/."""
    path = path.expanduser()
    if path.is_absolute():
        return path
    return output_dir(*output_subfolders) / path
