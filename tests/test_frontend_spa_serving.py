"""새 React 프론트(web/dist) 서빙 — SPA 폴백은 화면 경로만 받고 API·파일 요청은 가로채지 않는다.

임시 폴더에 가짜 빌드를 만들어 검사하므로 npm 빌드가 없어도 돈다(src/frontend_serving.py)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.frontend_serving import mount_frontend, resolve_mode


@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return root


@pytest.fixture()
def legacy(tmp_path):
    root = tmp_path / "frontend"
    for name in ("css", "js", "assets"):
        (root / name).mkdir(parents=True)
    (root / "index.html").write_text("<title>legacy</title>", encoding="utf-8")
    (root / "signup.html").write_text("<title>legacy signup</title>", encoding="utf-8")
    (root / "CLAUDE.md").write_text("dev notes", encoding="utf-8")
    return root


def _app(dist, legacy, mode=None):
    app = FastAPI()

    @app.get("/auth/me")
    def me():  # 진짜 API 라우터가 먼저 등록된 상황을 흉내 낸다
        return {"api": True}

    used = mount_frontend(app, web_dist=dist, legacy_dir=legacy, mode=mode)
    return app, used


def test_auto_mode_prefers_the_built_spa(dist, legacy):
    _, used = _app(dist, legacy)
    assert used == "spa"


def test_auto_mode_falls_back_to_legacy_when_not_built(tmp_path, legacy):
    _, used = _app(tmp_path / "missing", legacy)
    assert used == "legacy"


def test_spa_mode_without_a_build_fails_loudly(tmp_path, legacy):
    with pytest.raises(RuntimeError, match="npm run build"):
        _app(tmp_path / "missing", legacy, mode="spa")


def test_unknown_mode_is_rejected(dist):
    with pytest.raises(ValueError):
        resolve_mode(dist, "bogus")


@pytest.mark.parametrize("path", ["/", "/plan", "/plan/confirm", "/plan/report/abc-123", "/check/review", "/login"])
def test_spa_routes_serve_index_html_so_refresh_works(dist, legacy, path):
    app, _ = _app(dist, legacy)
    r = TestClient(app).get(path)
    assert r.status_code == 200
    assert "<title>spa</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_head_requests_are_answered_for_health_probes(dist, legacy):
    app, _ = _app(dist, legacy)
    assert TestClient(app).head("/").status_code == 200
    assert TestClient(app).head("/plan").status_code == 200


def test_spa_serves_built_assets(dist, legacy):
    app, _ = _app(dist, legacy)
    r = TestClient(app).get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_real_api_routes_win_over_the_fallback(dist, legacy):
    app, _ = _app(dist, legacy)
    assert TestClient(app).get("/auth/me").json() == {"api": True}


@pytest.mark.parametrize("path", ["/auth/unknown", "/session/x/nope", "/lists/x/y", "/openapi.json/x", "/missing.js", "/logo.png", "/assets/none.js"])
def test_unknown_api_paths_and_files_are_404_not_index_html(dist, legacy, path):
    app, _ = _app(dist, legacy)
    r = TestClient(app).get(path)
    assert r.status_code == 404
    assert "<title>spa</title>" not in r.text


def test_legacy_mode_keeps_the_old_behaviour(dist, legacy):
    app, used = _app(dist, legacy, mode="legacy")
    assert used == "legacy"
    c = TestClient(app)
    assert "legacy" in c.get("/").text
    assert c.get("/signup.html").status_code == 200
    assert c.get("/CLAUDE.md").status_code == 404      # 개발 문서는 노출하지 않는다
    assert c.get("/plan").status_code == 404            # SPA 경로 폴백은 spa 모드만
