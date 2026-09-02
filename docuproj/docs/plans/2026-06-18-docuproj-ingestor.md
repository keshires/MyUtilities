# DocuProj Ingestor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the DocuProj Ingestor — read a `project.json`, clone/fetch each listed repo, check out the selected branch, always fetch latest, and record the resolved HEAD SHA + local path for every repo.

**Architecture:** A `load_project()` maps the input JSON (`{project, repos:[{url, folder, branch}]}`) onto the existing `Project`/`RepoRef` model. A thin `git` subprocess wrapper (`run_git`, `head_sha`) backs `clone_or_update()`, which clones a fresh repo or fetches-and-resets an existing one to `origin/<branch>`. `ingest()` orchestrates per-repo into `DocuProj/.workspace/<project>/<folder>` (gitignored) and returns `ResolvedRepo` records.

**Tech Stack:** Python 3.11+, pydantic v2, `git` via `subprocess`, pytest. Tests run against disposable local git repos created in `tmp_path` — no network, no private-repo access.

---

## Roadmap context (where this fits)

**Plan 2 of the Phase-1 MVP vertical.** Depends on Plan 1's `Project`/`RepoRef` models. Produces resolved, on-disk source trees at pinned SHAs — the input the Parsers (Plan 3) consume. The `.workspace/` clone location is already gitignored (Plan 1).

## File Structure

```
DocuProj/
  engine/
    ingest.py            # load_project(), run_git(), head_sha(), clone_or_update(), ingest(), ResolvedRepo
  projects/
    edfx-flow.json       # sample input: the 6-repo EDFX fleet (§2 of the spec)
  tests/
    test_ingest.py       # offline tests against local fixture repos
```

`ingest.py` owns everything ingestion-related (one responsibility: turn a project spec into resolved local checkouts). `projects/edfx-flow.json` is the canonical sample config (not cloned by tests — it points at private repos).

---

### Task 1: `load_project()` and the sample `edfx-flow.json`

**Files:**
- Create: `DocuProj/engine/ingest.py`
- Create: `DocuProj/projects/edfx-flow.json`
- Test: `DocuProj/tests/test_ingest.py`

The input file uses `project` (a string) + `repos[{url, folder, branch}]`; `load_project` maps `project` to both `Project.id` and `Project.name`, and each repo to a `RepoRef` (sha unset until ingest).

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_ingest.py`

```python
from pathlib import Path

from engine.ingest import load_project


def test_load_project_maps_input_json(tmp_path):
    pj = tmp_path / "p.json"
    pj.write_text(
        '{"project": "edfx-flow", "repos": [{"url": "u", "folder": "f", "branch": "main"}]}',
        encoding="utf-8",
    )
    project = load_project(pj)
    assert project.id == "edfx-flow"
    assert project.name == "edfx-flow"
    assert project.repos[0].folder == "f"
    assert project.repos[0].branch == "main"
    assert project.repos[0].sha is None


def test_sample_edfx_flow_loads():
    sample = Path(__file__).resolve().parents[1] / "projects" / "edfx-flow.json"
    project = load_project(sample)
    assert project.id == "edfx-flow"
    assert len(project.repos) == 6
    assert all(r.branch for r in project.repos)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ingest'`.

- [ ] **Step 3: Write minimal implementation** — `DocuProj/engine/ingest.py`

```python
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
```

- [ ] **Step 4: Create the sample** — `DocuProj/projects/edfx-flow.json`

```json
{
  "project": "edfx-flow",
  "repos": [
    {"url": "https://github.com/moodysanalytics/edfx-app-ui", "folder": "edfx-app-ui", "branch": "main"},
    {"url": "https://github.com/moodysanalytics/edfx-api", "folder": "edfx-api", "branch": "main"},
    {"url": "https://github.com/moodysanalytics/edfx_entity_api", "folder": "edfx_entity_api", "branch": "main"},
    {"url": "https://github.com/moodysanalytics/edfx-client-financials-api", "folder": "edfx-client-financials-api", "branch": "main"},
    {"url": "https://github.com/moodysanalytics/edfx-tessera-service", "folder": "edfx-tessera-service", "branch": "main"},
    {"url": "https://github.com/moodysanalytics/edfx-report-builder", "folder": "edfx-report-builder", "branch": "main"}
  ]
}
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_ingest.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/engine/ingest.py DocuProj/projects/edfx-flow.json DocuProj/tests/test_ingest.py
git commit -m "feat(ingest): load_project and sample edfx-flow.json"
```

---

### Task 2: `run_git`, `head_sha`, and fresh-clone path of `clone_or_update`

**Files:**
- Modify: `DocuProj/engine/ingest.py`
- Test: `DocuProj/tests/test_ingest.py` (append helpers + tests)

`run_git` wraps `subprocess`, raising on non-zero exit. `head_sha` returns the resolved HEAD. `clone_or_update` clones with `--branch` when the destination has no `.git` yet.

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_ingest.py`

```python
import subprocess

from engine.ingest import clone_or_update, head_sha


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_upstream(path: Path, content: str = "v1") -> str:
    """Create a local git repo with one commit on branch 'main'. Returns HEAD sha."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init"], path)
    _git(["config", "user.email", "t@t.test"], path)
    _git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", "init"], path)
    _git(["branch", "-M", "main"], path)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(path), capture_output=True, text=True
    )
    return out.stdout.strip()


def test_head_sha_returns_full_commit(tmp_path):
    up = tmp_path / "up"
    sha = _make_upstream(up)
    assert head_sha(up) == sha
    assert len(sha) == 40


def test_clone_or_update_clones_fresh(tmp_path):
    up = tmp_path / "up"
    sha = _make_upstream(up)
    dest = tmp_path / "ws" / "r"
    clone_or_update(str(up), dest, "main")
    assert (dest / ".git").exists()
    assert head_sha(dest) == sha
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_ingest.py -v`
Expected: FAIL with `ImportError: cannot import name 'clone_or_update'`.

- [ ] **Step 3: Write minimal implementation** — update `DocuProj/engine/ingest.py`

Replace the import block at the top so it reads:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from engine.models import Project, RepoRef
```

Append these functions:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_ingest.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/ingest.py DocuProj/tests/test_ingest.py
git commit -m "feat(ingest): add run_git, head_sha, and fresh-clone path"
```

---

### Task 3: Update path, `ingest()`, branch overrides, and exports

**Files:**
- Modify: `DocuProj/engine/ingest.py`
- Modify: `DocuProj/engine/__init__.py`
- Test: `DocuProj/tests/test_ingest.py` (append)

`clone_or_update`'s update branch is already implemented (Task 2); this task proves it fetches latest, then adds `ResolvedRepo` + `ingest()` (with per-folder branch overrides → file default), and exports the new public names.

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_ingest.py`

```python
from engine.ingest import ResolvedRepo, ingest
from engine.models import Project, RepoRef


def test_clone_or_update_fetches_latest(tmp_path):
    up = tmp_path / "up"
    _make_upstream(up, "v1")
    dest = tmp_path / "ws" / "r"
    clone_or_update(str(up), dest, "main")
    # advance upstream
    (up / "README.md").write_text("v2", encoding="utf-8")
    _git(["add", "."], up)
    _git(["commit", "-m", "v2"], up)
    new_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(up), capture_output=True, text=True
    ).stdout.strip()
    clone_or_update(str(up), dest, "main")
    assert head_sha(dest) == new_sha


def test_ingest_resolves_repos(tmp_path):
    up = tmp_path / "up"
    sha = _make_upstream(up)
    project = Project(id="proj", name="proj", repos=[RepoRef(url=str(up), folder="r", branch="main")])
    ws = tmp_path / "workspace"
    resolved = ingest(project, ws)
    assert len(resolved) == 1
    r = resolved[0]
    assert isinstance(r, ResolvedRepo)
    assert r.folder == "r"
    assert r.branch == "main"
    assert r.sha == sha
    assert Path(r.path) == ws / "proj" / "r"
    assert (Path(r.path) / ".git").exists()


def test_ingest_applies_branch_override(tmp_path):
    up = tmp_path / "up"
    _make_upstream(up)
    _git(["checkout", "-b", "feature"], up)
    (up / "f.txt").write_text("x", encoding="utf-8")
    _git(["add", "."], up)
    _git(["commit", "-m", "feat"], up)
    feat_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(up), capture_output=True, text=True
    ).stdout.strip()
    _git(["checkout", "main"], up)
    project = Project(id="proj", name="proj", repos=[RepoRef(url=str(up), folder="r", branch="main")])
    ws = tmp_path / "workspace"
    resolved = ingest(project, ws, branch_overrides={"r": "feature"})
    assert resolved[0].branch == "feature"
    assert resolved[0].sha == feat_sha
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_ingest.py -v`
Expected: FAIL with `ImportError: cannot import name 'ResolvedRepo'`.

- [ ] **Step 3: Write minimal implementation** — update `DocuProj/engine/ingest.py`

Add `BaseModel` to the imports (new line after the json/subprocess imports):

```python
from pydantic import BaseModel
```

Add the `ResolvedRepo` model immediately after the imports (before `load_project`):

```python
class ResolvedRepo(BaseModel):
    """One repo resolved to a local checkout at a pinned SHA."""

    url: str
    folder: str
    branch: str
    sha: str
    path: str
```

Append `ingest()` at the end of the file:

```python
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
```

Then add the ingest exports to `DocuProj/engine/__init__.py`. Add this import after the existing `from engine.models import (...)` block:

```python
from engine.ingest import ResolvedRepo, ingest, load_project
```

And extend `__all__` with the three new names (insert in alphabetical position):

```python
    "ResolvedRepo",
    "ingest",
    "load_project",
```

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -v`
Expected: PASS (all Plan 1 + Plan 2 tests — 16 prior + 7 new = 23).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/ingest.py DocuProj/engine/__init__.py DocuProj/tests/test_ingest.py
git commit -m "feat(ingest): add ResolvedRepo, ingest() orchestration, and exports"
```

---

## Self-Review

**Spec coverage (Ingestor, §3 / §2 / §9):**
- Reads `project.json` (`{project, repos:[{url, folder, branch}]}`) — Task 1 ✓
- Clone if absent, else fetch — Task 2 (clone) + Task 3 (fetch latest) ✓
- Checkout selected branch with override → file default precedence — Task 3 (`branch_overrides`) ✓
- Always fetch latest before a run (`reset --hard origin/<branch>`) — Task 2/3 ✓
- Record resolved HEAD SHA — Task 2 (`head_sha`) + Task 3 (in `ResolvedRepo`) ✓
- Clones under `.workspace/<project>/<folder>` (gitignored) — Task 3 (`workspace_root / project.id / repo.folder`) ✓
- Interface `ingest(...) -> [{repo, folder, branch, sha, path}]` — Task 3 (`ResolvedRepo`) ✓
- Sample EDFX input (6 repos) — Task 1 ✓
- Out of scope here (later plans): parsing (Plan 3), Git Credential Manager auth is implicit (plain `git`, already authenticated per spec §2).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows command + expected result.

**Type consistency:** `load_project`, `run_git`, `head_sha`, `clone_or_update(url, dest, branch)`, `ingest(project, workspace_root, branch_overrides)`, and `ResolvedRepo{url, folder, branch, sha, path}` are referenced identically across tasks and tests. `branch_overrides` is keyed by `folder` everywhere.
