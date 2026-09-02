"""Scan logs/ and output/ for a utility's recent runs and artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import project_paths
from dashboard.manifest import Utility


class RunFile(TypedDict):
    kind: str
    name: str
    mtime: float
    size: int
    summary: dict | None


def _base(kind: str) -> Path:
    return project_paths.logs_dir() if kind == "log" else project_paths.output_dir()


def _read_summary(path: Path, suffix: str | None) -> dict | None:
    if not suffix:
        return None
    sidecar = path.with_name(path.name + suffix)
    if not sidecar.exists():
        # Also try replacing the extension (e.g. foo.log -> foo.summary.json).
        sidecar = path.with_suffix("").with_name(path.stem + suffix)
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_runs(util: Utility, limit: int = 20) -> list[RunFile]:
    runs: list[RunFile] = []
    pairs = [("log", util.outputs.logs_glob), ("output", util.outputs.output_glob)]
    for kind, glob in pairs:
        if not glob:
            continue
        base = _base(kind)
        if not base.exists():
            continue
        for p in base.glob(glob):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            runs.append(
                RunFile(
                    kind=kind,
                    name=str(p.relative_to(base)).replace("\\", "/"),
                    mtime=st.st_mtime,
                    size=st.st_size,
                    summary=_read_summary(p, util.outputs.summary_suffix),
                )
            )
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs[:limit]


def resolve_artifact(kind: str, name: str) -> Path | None:
    if kind not in ("log", "output"):
        return None
    base = _base(kind).resolve()
    target = (base / name).resolve()
    if base not in target.parents and target != base:
        return None
    if not target.is_file():
        return None
    return target
