"""One-step setup for DocuProj: create the virtualenv, install dependencies, and
clone the default EDFX repo chain so `flow.py` / the dashboard work immediately.

Idempotent — re-running skips a venv that exists, an install that's current, and any
repo already cloned. Run from the DocuProj/ directory with the system Python:

    python bootstrap.py                 # venv + install + clone the default chain
    python bootstrap.py --skip-clone    # venv + install only (offline / CI / no repo access)
    python bootstrap.py --repos a,b     # clone only these folder names from the chain

Edit DEFAULT_CHAIN below to change which repos a bare run clones. Branches matter:
edfx-api is `master`, the rest `main` (see ../shared/REPOS.md).
"""

import subprocess
import sys
from pathlib import Path

ORG = "https://github.com/moodysanalytics"
WS = Path(".workspace/edfx-flow")
VENV = Path(".venv")

# (folder, language, branch) — the UI -> gateway -> service -> DB chain documented in the README.
# `language` is informational here; flow.py auto-detects it. Add rows from ../shared/REPOS.md as needed.
DEFAULT_CHAIN = [
    ("edfx-app-ui", "angular", "main"),
    ("edfx-api", "python", "master"),
    ("edfx-tessera-service", "python", "main"),
]


def _venv_python() -> Path:
    """Path to the interpreter inside the venv (Scripts on Windows, bin elsewhere)."""
    return VENV / ("Scripts" if sys.platform == "win32" else "bin") / (
        "python.exe" if sys.platform == "win32" else "python"
    )


def ensure_venv() -> None:
    if _venv_python().exists():
        print(f"venv: {VENV} already present — skipping create")
        return
    print(f"venv: creating {VENV} ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)


def install_deps() -> None:
    py = _venv_python()
    print("deps: installing requirements.txt into the venv ...")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], check=True)
    print("deps: done")


def clone_repos(only: set[str] | None) -> None:
    WS.mkdir(parents=True, exist_ok=True)
    for folder, _lang, branch in DEFAULT_CHAIN:
        if only is not None and folder not in only:
            continue
        dest = WS / folder
        if dest.exists():
            print(f"repo: {folder} already cloned — skipping")
            continue
        url = f"{ORG}/{folder}"
        print(f"repo: cloning {folder} (branch {branch}) ...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, url, str(dest)]
        )
        if result.returncode != 0:
            print(f"  ! clone failed for {folder} — check access/branch (see ../shared/REPOS.md). Continuing.")


def main() -> int:
    argv = sys.argv[1:]
    skip_clone = "--skip-clone" in argv
    only: set[str] | None = None
    for a in argv:
        if a.startswith("--repos"):
            _, _, val = a.partition("=")
            if not val and argv.index(a) + 1 < len(argv):  # support "--repos a,b"
                val = argv[argv.index(a) + 1]
            only = {s.strip() for s in val.split(",") if s.strip()}

    ensure_venv()
    install_deps()
    if skip_clone:
        print("clone: skipped (--skip-clone)")
    else:
        clone_repos(only)

    py = _venv_python()
    print(
        "\nReady. Next:\n"
        f"  {py} flow.py portfolios          # trace an endpoint's data provenance\n"
        f"  {py} -m uvicorn serve_demo:app --host 127.0.0.1 --port 8011   # dashboard at /app/\n"
        f"  {py} -m pytest                   # run the test suite"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
