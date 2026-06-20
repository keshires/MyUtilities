from engine.analyze import detect_language


def test_detect_angular(tmp_path):
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "angular"


def test_detect_python(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert detect_language(tmp_path) == "python"


def test_detect_typescript(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "typescript"


def test_detect_unknown(tmp_path):
    assert detect_language(tmp_path) is None
