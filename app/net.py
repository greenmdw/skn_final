"""
분산 서비스 간 HTTP 호출 (stdlib urllib만 사용 — 새 의존성 없음).

broker → seller, buyer → broker 호출에 쓴다.
테스트에서는 set_dispatcher()로 실제 네트워크 대신 in-process 앱으로 라우팅할 수 있다.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable

# (method, url, body_dict) -> (status_code, response_dict)
Dispatcher = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]

_dispatcher: Dispatcher | None = None


def set_dispatcher(fn: Dispatcher | None) -> None:
    """테스트 훅: 모든 post_json/get_json을 이 함수로 돌린다. None이면 실제 HTTP."""
    global _dispatcher
    _dispatcher = fn


class HttpCallError(RuntimeError):
    def __init__(self, url: str, detail: str) -> None:
        super().__init__(f"{url} 호출 실패: {detail}")
        self.url = url
        self.detail = detail


def _real_call(method: str, url: str, body: dict[str, Any] | None, timeout: float) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"detail": raw.decode("utf-8", "replace")}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise HttpCallError(url, str(exc)) from exc


def post_json(url: str, body: dict[str, Any], *, timeout: float = 10.0) -> tuple[int, Any]:
    if _dispatcher is not None:
        return _dispatcher("POST", url, body)
    return _real_call("POST", url, body, timeout)


def get_json(url: str, *, timeout: float = 10.0) -> tuple[int, Any]:
    if _dispatcher is not None:
        return _dispatcher("GET", url, None)
    return _real_call("GET", url, None, timeout)
