"""프론트 정적 서빙 — React 앱(web/dist)이 빌드돼 있으면 그것을 같은 오리진에서 낸다.

빌드가 없으면 프론트 없이 API만 뜬다(`cd web && npm install && npm run build` 로 만든다).
BrowserRouter 경로를 새로고침해도 열리도록 index.html 로 폴백하되, API 경로와 파일 요청(.js/.png …)은
폴백하지 않는다 — 없는 API 경로가 index.html(200)로 답하면 오류가 숨는다.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# API 가 쓰는 최상위 경로. SPA 폴백이 가로채지 않는다(라우터가 먼저 등록되므로 실제 API 는 영향 없고,
# 없는 하위 경로만 404 로 남는다).
API_PREFIXES = frozenset({"auth", "session", "lists", "reviews", "pc", "dev", "docs", "redoc", "openapi.json", "health"})


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


def mount_frontend(app: FastAPI, *, web_dist: Path) -> str:
    """프론트를 앱에 붙이고 'spa' 또는 'none'(빌드 없음)을 돌려준다. API 라우터를 모두 등록한 뒤 마지막에 부른다."""
    if not (web_dist / "index.html").is_file():
        return "none"
    _mount_spa(app, web_dist)
    return "spa"
