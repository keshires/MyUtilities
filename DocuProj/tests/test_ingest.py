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
