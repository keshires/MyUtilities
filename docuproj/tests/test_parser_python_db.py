from pathlib import Path

from engine.parsers.python_db import extract_python_db

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_db"


def test_extract_python_db():
    accesses = extract_python_db(_FIX, repo="edfx-api")
    engines = {a.engine for a in accesses}
    assert "sqlalchemy" in engines
    assert "raw_sql" in engines

    orm = next(a for a in accesses if a.engine == "sqlalchemy")
    assert orm.detail == "Portfolio"
    assert orm.code_ref.file == "repo.py"
    assert orm.code_ref.line >= 1

    raw = next(a for a in accesses if a.engine == "raw_sql")
    assert "portfolios" in raw.detail