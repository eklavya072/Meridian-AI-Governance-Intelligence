"""The API serves a static export of the web app when FRONTEND_DIST is set."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<h1>home</h1>")
    (tmp_path / "analysis.html").write_text("<h1>analysis</h1>")
    (tmp_path / "404.html").write_text("<h1>missing</h1>")
    (tmp_path / "_next" / "static").mkdir(parents=True)
    (tmp_path / "_next" / "static" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))

    import main

    reloaded = importlib.reload(main)
    yield TestClient(reloaded.app)
    monkeypatch.delenv("FRONTEND_DIST")
    importlib.reload(main)


def test_the_home_page_is_served(client):
    assert "home" in client.get("/").text


def test_a_page_is_served_without_its_extension(client):
    assert "analysis" in client.get("/analysis").text


def test_build_assets_are_cached_for_good(client):
    response = client.get("/_next/static/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_an_unknown_page_is_the_404_page(client):
    response = client.get("/nowhere")
    assert response.status_code == 404
    assert "missing" in response.text


def test_an_unknown_api_path_stays_a_json_404(client):
    response = client.get("/api/v1/nowhere")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_nothing_outside_the_export_is_reachable(client):
    assert client.get("/../main.py").status_code == 404
    assert client.get("/%2e%2e/main.py").status_code == 404


def test_the_api_still_answers(client):
    assert client.get("/healthz").json()["status"] == "ok"
