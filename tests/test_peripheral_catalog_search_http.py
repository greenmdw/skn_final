"""작업지시서 W-1 — 주변기기 제품 검색 API (`GET /peripherals/catalog/search`).

커뮤니티 글쓰기 화면이 "어떤 제품인지" 고를 때 쓴다. 옵션 분리(`split_switch_options`)는 DB 없이
단위 테스트하고, 검색 자체는 시드가 들어간 일회용 DB 로 검사한다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.engine.peripheral_parse import split_switch_options

DSN = os.getenv("DATABASE_URL")


def needs_db(fn):
    """DB 가 필요한 테스트 표시 — 위 옵션 분리 테스트는 DB 없이 돈다."""
    return pytest.mark.db(pytest.mark.skipif(not DSN, reason="일회용 DB 필요")(fn))


if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from src.db import get_conn


# --- 옵션 분리: DB 없이 ---------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("GL Linear / GL Tactile / GL Clicky", ["GL Linear", "GL Tactile", "GL Clicky"]),
    ("CHERRY MX2A Red / Brown / Blue / Silent Red 등", ["CHERRY MX2A Red", "Brown", "Blue", "Silent Red"]),
    ("CORSAIR MLX Red", ["CORSAIR MLX Red"]),
    ("—", []),
    ("", []),
    (None, []),
    ("   ", []),
    ("TTC 40g/45g", ["TTC 40g/45g"]),            # 붙어 있는 슬래시는 나누지 않는다
    ("Red / Red / Brown", ["Red", "Brown"]),     # 중복 제거
])
def test_split_switch_options(raw, expected):
    assert split_switch_options(raw) == expected


# --- 검색 API: 일회용 DB ---------------------------------------------------------------

def _search(client, **params) -> list[dict]:
    r = client.get("/peripherals/catalog/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


@pytest.fixture()
def client():
    return TestClient(app)


@needs_db
@pytest.mark.parametrize("kind", ["monitor", "keyboard", "mouse", "speaker"])
def test_search_returns_only_requested_kind(client, kind):
    items = _search(client, kind=kind, limit=30)
    assert items
    assert {i["kind"] for i in items} == {kind}


@needs_db
@pytest.mark.parametrize("q", ["gpro", "GPRO", "g pro", "G PRO X"])
def test_search_ignores_case_and_spaces(client, q):
    names = {f"{i['brand']} {i['model']}" for i in _search(client, kind="mouse", q=q)}
    assert "Logitech G PRO X SUPERLIGHT 2" in names


@needs_db
def test_search_fc900_finds_keyboard_with_options(client):
    items = _search(client, kind="keyboard", q="FC900")
    assert [i["model"] for i in items][:1] == ["FC900RBT MX2A"]
    assert items[0]["options"] == ["CHERRY MX2A Red", "Brown", "Blue", "Silent Red"]


@needs_db
def test_search_multiple_words_must_all_match(client):
    items = _search(client, kind="mouse", q="logitech lift")
    assert items and all("lift" in i["model"].lower() for i in items)
    assert _search(client, kind="mouse", q="logitech zzzznomatch") == []


@needs_db
def test_search_orders_model_prefix_first(client):
    items = _search(client, kind="mouse", q="G PRO X", limit=30)
    assert items[0]["model"].lower().startswith("g pro x")


@needs_db
def test_search_non_keyboard_options_are_empty(client):
    for kind in ("monitor", "mouse", "speaker"):
        assert all(i["options"] == [] for i in _search(client, kind=kind, limit=30))


@needs_db
def test_search_empty_query_lists_kind_by_name(client):
    items = _search(client, kind="speaker", limit=30)
    with get_conn() as conn:
        expected = conn.execute(
            "SELECT id::text FROM catalog.product WHERE product_type = 'speaker' AND status = 'active' "
            "ORDER BY brand, model LIMIT 30"
        ).fetchall()
    assert [i["product_id"] for i in items] == [r[0] for r in expected]
    assert items == _search(client, kind="speaker", q="", limit=30)


@needs_db
def test_search_includes_products_without_price(client):
    model = f"NOPRICE-{uuid4().hex[:8]}"
    with get_conn() as conn:
        pid = conn.execute(
            "INSERT INTO catalog.product (name, brand, model, product_type) VALUES (%s, 'TestBrand', %s, 'mouse') RETURNING id",
            (f"TestBrand {model}", model),
        ).fetchone()[0]
    try:
        items = _search(client, kind="mouse", q=model)
        assert [i["product_id"] for i in items] == [str(pid)]
        assert items[0]["options"] == []
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM catalog.product WHERE id = %s", (pid,))


@needs_db
def test_search_excludes_discontinued_products(client):
    model = f"OLD-{uuid4().hex[:8]}"
    with get_conn() as conn:
        pid = conn.execute(
            "INSERT INTO catalog.product (name, brand, model, product_type, status) "
            "VALUES (%s, 'TestBrand', %s, 'mouse', 'discontinued') RETURNING id",
            (f"TestBrand {model}", model),
        ).fetchone()[0]
    try:
        assert _search(client, kind="mouse", q=model) == []
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM catalog.product WHERE id = %s", (pid,))


@needs_db
def test_search_treats_like_wildcards_literally(client):
    assert _search(client, kind="mouse", q="%") == []
    assert _search(client, kind="mouse", q="_") == []


@needs_db
def test_search_invalid_kind_is_422(client):
    assert client.get("/peripherals/catalog/search", params={"kind": "gpu"}).status_code == 422
    assert client.get("/peripherals/catalog/search").status_code == 422


@needs_db
def test_search_limit_bounds(client):
    assert len(_search(client, kind="mouse", limit=30)) <= 30
    assert len(_search(client, kind="mouse", limit=2)) == 2
    assert client.get("/peripherals/catalog/search", params={"kind": "mouse", "limit": 31}).status_code == 422
    assert client.get("/peripherals/catalog/search", params={"kind": "mouse", "limit": 0}).status_code == 422
