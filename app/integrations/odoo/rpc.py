"""
Odoo JSON-2 ORM 호출 헬퍼 — search_read / create / write / 임의 메서드.

기존 client.py(연결 확인 전용)는 건드리지 않고 그 위에 얹는다.
JSON-2 API(/json/2/<model>/<method>)의 바디 형태는 Odoo 버전에 따라 미세하게 다를 수 있어
**여기 한 곳만 고치면** 전체가 맞춰지도록 격리했다. (Odoo 19 라이브에서 1회 검증 필요)

모든 메서드는 실패 시 예외를 그대로 올린다 — 호출부(sync.py)에서 best-effort 로 감싼다.
"""

from __future__ import annotations

from typing import Any

from .client import OdooJson2Client


def _unwrap(res: Any) -> Any:
    """JSON-2 가 결과를 그대로 주기도 하고 {"result": ...} 로 감싸기도 한다."""
    if isinstance(res, dict) and set(res.keys()) <= {"result", "error"} and "result" in res:
        return res["result"]
    return res


class OdooRpc:
    def __init__(self, client: OdooJson2Client) -> None:
        self.c = client

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str],
        *,
        limit: int = 50,
        order: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"domain": domain, "fields": fields, "limit": limit}
        if order:
            params["order"] = order
        res = _unwrap(self.c.call(model, "search_read", params))
        return res if isinstance(res, list) else []

    def create(self, model: str, vals: dict) -> int | None:
        """레코드 1건 생성 → id. Odoo 18+ 는 배치(create(vals_list)) 라 vals_list 로 보낸다."""
        res = _unwrap(self.c.call(model, "create", {"vals_list": [vals]}))
        if isinstance(res, list) and res:
            return int(res[0])
        if isinstance(res, int):
            return res
        return None

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        res = _unwrap(self.c.call(model, "write", {"ids": ids, "vals": vals}))
        return bool(res) if res is not None else True

    def method(self, model: str, name: str, ids: list[int] | None = None, **kwargs: Any) -> Any:
        params: dict[str, Any] = dict(kwargs)
        if ids is not None:
            params["ids"] = ids
        return _unwrap(self.c.call(model, name, params))

    # 편의 --------------------------------------------------------------
    def post_note(self, model: str, rec_id: int, body: str) -> None:
        """레코드 chatter 에 노트 한 줄 (GUI 타임라인에 표시)."""
        self.method(
            model, "message_post", ids=[rec_id],
            body=body, message_type="comment", subtype_xmlid="mail.mt_note",
        )
