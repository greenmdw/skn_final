"""프론트 정적 서빙 — 새 React 앱(web/dist)이 빌드돼 있으면 그것을, 아니면 옛 정적 프론트(frontend/)를 낸다.

모드(env TRUEFIT_FRONTEND):
  auto    (기본) web/dist/index.html 이 있으면 spa, 없으면 legacy
  spa     새 React 앱만. 빌드가 없으면 시작 시 오류로 알린다
  legacy  옛 frontend/ 만 (테스트와 비교용)

spa 모드는 BrowserRouter 경로(/plan, /plan/confirm …)를 새로고침해도 열리도록 index.html 로 폴백한다.
단, API 경로와 파일 요청(.js/.png …)은 폴백하지 않는다 — 없는 API 경로가 index.html(200)로 답하면
오류가 숨는다.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# API 가 쓰는 최상위 경로. SPA 폴백이 가로채지 않는다(라우터가 먼저 등록되므로 실제 API 는 영향 없고,
# 없는 하위 경로만 404 로 남는다).
API_PREFIXES = frozenset({"auth", "session", "lists", "reviews", "dev", "docs", "redoc", "openapi.json", "health"})

MODES = ("auto", "spa", "legacy")


def resolve_mode(web_dist: Path, requested: str | None) -> str:
    choice = (requested or "auto").strip().lower()
    if choice not in MODES:
        raise ValueError(f"TRUEFIT_FRONTEND 는 {'|'.join(MODES)} 중 하나여야 합니다: {requested!r}")
    built = (web_dist / "index.html").is_file()
    if choice == "auto":
        return "spa" if built else "legacy"
    if choice == "spa" and not built:
        raise RuntimeError(f"새 프론트 빌드가 없습니다: {web_dist / 'index.html'} — `cd web && npm ci && npm run build`")
    return choice


def _mount_legacy(app: FastAPI, legacy_dir: Path) -> None:
    # 공개할 프런트 파일만 각각 마운트해 frontend/ 안의 개발 문서 등은 노출하지 않는다.
    app.mount("/css", StaticFiles(directory=legacy_dir / "css"), name="frontend-css")
    app.mount("/js", StaticFiles(directory=legacy_dir / "js"), name="frontend-js")
    app.mount("/assets", StaticFiles(directory=legacy_dir / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(legacy_dir / "index.html")

    @app.get("/{page_name}.html", include_in_schema=False)
    def frontend_page(page_name: str) -> FileResponse:
        """Serve only top-level frontend HTML pages, never arbitrary frontend files."""
        page = legacy_dir / f"{page_name}.html"
        if not page.is_file() or page.parent != legacy_dir:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(page)


def _mount_spa(app: FastAPI, web_dist: Path) -> None:
    index = web_dist / "index.html"
    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")

    # index.html 은 매 빌드마다 해시가 다른 자산을 가리키므로 캐시하지 않는다.
    no_cache = {"Cache-Control": "no-cache"}

    # HEAD 도 받는다 — 상태 확인·링크 검사기가 HEAD / 로 살아 있는지 본다.
    @app.api_route("/{route_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa_fallback(route_path: str) -> FileResponse:
        parts = route_path.split("/")
        if parts[0] in API_PREFIXES or "." in parts[-1]:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers=no_cache)


def mount_frontend(app: FastAPI, *, web_dist: Path, legacy_dir: Path, mode: str | None = None) -> str:
    """프론트를 앱에 붙이고 실제로 쓴 모드('spa'|'legacy')를 돌려준다. API 라우터를 모두 등록한 뒤 마지막에 부른다."""
    resolved = resolve_mode(web_dist, mode)
    if resolved == "spa":
        _mount_spa(app, web_dist)
    else:
        _mount_legacy(app, legacy_dir)
    return resolved
