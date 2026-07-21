import os
from pathlib import Path

import pytest

import portfolio_kpi_metrics_postgres as mod

_KEYS = ("KPI_T_OSWIN", "KPI_T_ENVFILE", "KPI_T_BASE")


@pytest.fixture(autouse=True)
def _clean_env():
    """Snapshot/restore the vars these tests touch (load_dotenv mutates os.environ)."""
    saved = {k: os.environ.get(k) for k in _KEYS}
    for k in _KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_precedence_os_then_envfile_then_base(tmp_path):
    (tmp_path / ".env.qa").write_text(
        "KPI_T_OSWIN=fromfile\nKPI_T_ENVFILE=fromqa\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "KPI_T_ENVFILE=frombase\nKPI_T_BASE=frombase\n", encoding="utf-8"
    )
    os.environ["KPI_T_OSWIN"] = "fromos"

    loaded = mod.load_env("qa", root=tmp_path)

    assert os.environ["KPI_T_OSWIN"] == "fromos"      # OS wins
    assert os.environ["KPI_T_ENVFILE"] == "fromqa"    # env-file beats base
    assert os.environ["KPI_T_BASE"] == "frombase"     # base fills gap
    assert [p.name for p in loaded] == [".env.qa", ".env"]


def test_missing_env_file_is_not_fatal(tmp_path):
    (tmp_path / ".env").write_text("KPI_T_BASE=frombase\n", encoding="utf-8")
    loaded = mod.load_env("nope", root=tmp_path)  # .env.nope does not exist
    assert [p.name for p in loaded] == [".env"]
    assert os.environ["KPI_T_BASE"] == "frombase"
