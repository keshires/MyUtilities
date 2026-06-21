from fastapi.testclient import TestClient

from engine.api import create_app


def _client(tmp_path):
    return TestClient(create_app(projects_dir=tmp_path, workspace=tmp_path / "ws", store={}))


def test_root_redirects_to_dashboard(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/app/"


def test_dashboard_index_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert "DocuProj" in resp.text
    assert 'id="endpoint-list"' in resp.text


def test_dashboard_assets_served(tmp_path):
    client = _client(tmp_path)
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/styles.css").status_code == 200


def test_index_wires_assets_and_mounts(tmp_path):
    client = _client(tmp_path)
    html = client.get("/app/").text
    assert "app.js" in html
    assert "styles.css" in html
    for marker in ('id="endpoint-list"', 'id="flow-canvas"', 'id="popup"'):
        assert marker in html
