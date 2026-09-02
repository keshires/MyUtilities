from pathlib import Path
import sys

# Will be importable after conftest.py is added in Task 9; for now verify the module directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
import project_paths


def test_project_root_resolves_to_app_folder():
    # This test file lives at edfx/tests/test_project_paths.py
    # parent.parent should be edfx/
    expected = Path(__file__).resolve().parent.parent
    assert project_paths.PROJECT_ROOT == expected


def test_logs_dir_under_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.logs_dir("run1")
    assert result == tmp_path / "logs" / "run1"
    assert result.exists()


def test_output_dir_under_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.output_dir("exports")
    assert result == tmp_path / "output" / "exports"
    assert result.exists()


def test_resolve_project_relative_absolute_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    abs_path = str(tmp_path / "some" / "file.csv")
    assert project_paths.resolve_project_relative(abs_path) == abs_path


def test_resolve_project_relative_joins_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    assert project_paths.resolve_project_relative("data/file.csv") == str(tmp_path / "data" / "file.csv")


def test_resolve_cli_artifact_relative_goes_under_output(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.resolve_cli_artifact(Path("report.csv"), "exports")
    assert result == tmp_path / "output" / "exports" / "report.csv"
