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
