"""새 React 프론트(web/dist) 서빙 — SPA 폴백은 화면 경로만 받고 API·파일 요청은 가로채지 않는다.

임시 폴더에 가짜 빌드를 만들어 검사하므로 npm 빌드가 없어도 돈다(src/frontend_serving.py)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.frontend_serving import mount_frontend


@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return root


def _app(dist):
    app = FastAPI()

    @app.get("/auth/me")
    def me():  # 진짜 API 라우터가 먼저 등록된 상황을 흉내 낸다
        return {"api": True}

    used = mount_frontend(app, web_dist=dist)
    return app, used


def test_built_spa_is_mounted(dist):
    _, used = _app(dist)
    assert used == "spa"


@pytest.mark.parametrize("path", ["/", "/plan", "/plan/confirm", "/plan/report/abc-123", "/check/review", "/login"])
def test_spa_routes_serve_index_html_so_refresh_works(dist, path):
    app, _ = _app(dist)
    r = TestClient(app).get(path)
    assert r.status_code == 200
    assert "<title>spa</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_head_requests_are_answered_for_health_probes(dist):
    app, _ = _app(dist)
    assert TestClient(app).head("/").status_code == 200
    assert TestClient(app).head("/plan").status_code == 200


def test_spa_serves_built_assets(dist):
    app, _ = _app(dist)
    r = TestClient(app).get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_real_api_routes_win_over_the_fallback(dist):
    app, _ = _app(dist)
    assert TestClient(app).get("/auth/me").json() == {"api": True}


@pytest.mark.parametrize("path", ["/auth/unknown", "/session/x/nope", "/lists/x/y", "/openapi.json/x", "/missing.js", "/logo.png", "/assets/none.js"])
def test_unknown_api_paths_and_files_are_404_not_index_html(dist, path):
    app, _ = _app(dist)
    r = TestClient(app).get(path)
    assert r.status_code == 404
    assert "<title>spa</title>" not in r.text

def test_without_a_build_only_the_api_is_served(tmp_path):
    app, used = _app(tmp_path / "missing")
    assert used == "none"
    c = TestClient(app)
    assert c.get("/auth/me").json() == {"api": True}
    assert c.get("/").status_code == 404
