"""마이페이지 서버 저장(개발요청 C-1·C-2): 내 현재 PC, 사용자별 JSON 문서, 견적서별 부가 정보."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app


@pytest.fixture(autouse=True)
def _loose_limits(monkeypatch):
    from src.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "SIGNUP_LIMIT_PER_MIN_IP", 1000)


def _signup(name: str = "저장시험") -> TestClient:
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"me-{uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": name,
                                      "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


@pytest.fixture()
def alice():
    return _signup("앨리스")


@pytest.fixture()
def bob():
    return _signup("밥")


GUEST_PATHS = [("get", "/me/pc"), ("put", "/me/pc"), ("delete", "/me/pc"), ("get", "/me/data"), ("get", "/me/data/workspace"),
               ("put", "/me/data/workspace"), ("delete", "/me/data/workspace"), ("get", "/lists/extras"),
               ("get", f"/lists/{uuid4()}/extras"), ("put", f"/lists/{uuid4()}/extras"), ("delete", f"/lists/{uuid4()}/extras")]


@pytest.mark.parametrize("method,path", GUEST_PATHS)
def test_every_endpoint_requires_login(method, path):
    kwargs = {"json": {"parts": {"cpu": "x"}, "value": 1, "extras": {}}} if method == "put" else {}
    r = getattr(TestClient(app), method)(path, **kwargs)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


# ── C-1 내 현재 PC ───────────────────────────────────────────────────────────────────
def test_my_pc_roundtrip_replace_and_delete(alice, bob):
    a, b = alice, bob
    assert a.get("/me/pc").json() is None                                              # 없으면 null
    pc = {"parts": {"cpu": "라이젠 5 7600", "gpu": "RTX 4060", "ram": "DDR5 16GB", "storage": "980 PRO 1TB", "board": "B650M", "psu": "700W", "cooler": "AK400", "case": "미들타워"},
          "source": "직접 입력", "title": "내 데스크톱"}
    saved = a.put("/me/pc", json=pc).json()
    assert saved["parts"] == pc["parts"] and saved["source"] == "직접 입력" and saved["title"] == "내 데스크톱" and saved["saved_at"]
    assert a.get("/me/pc").json() == saved                                              # 다른 요청(=다른 브라우저)에서도 같은 값
    replaced = a.put("/me/pc", json={"parts": {"cpu": "  인텔   i5-14400  ", "gpu": ""}}).json()
    assert replaced["parts"] == {"cpu": "인텔 i5-14400"} and replaced["title"] == "" and replaced["source"] == ""   # 전체 교체, 공백 정리, 빈 칸 제거
    assert b.get("/me/pc").json() is None                                               # 다른 사용자에게는 보이지 않는다
    assert a.delete("/me/pc").status_code == 204 and a.delete("/me/pc").status_code == 204          # 멱등
    assert a.get("/me/pc").json() is None


def test_my_pc_validation(alice):
    a = alice
    assert a.put("/me/pc", json={"parts": {}}).status_code == 422                       # 한 칸 이상
    assert a.put("/me/pc", json={"parts": {"cpu": "   "}}).status_code == 422
    bad = a.put("/me/pc", json={"parts": {"cpu": "x", "monitor": "모니터"}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_part"     # 칸 이름은 고정
    assert a.put("/me/pc", json={"parts": {"cpu": "가" * 121}}).status_code == 422
    assert a.put("/me/pc", json={"parts": {"cpu": "가" * 120}}).status_code == 200
    assert a.put("/me/pc", json={"parts": {"cpu": "x"}, "title": "가" * 101}).status_code == 422
    assert a.put("/me/pc", json={"parts": {"cpu": "x"}, "source": "가" * 201}).status_code == 422
    assert a.put("/me/pc", json={"parts": {"cpu": 123}}).status_code == 422             # 값은 문자열
    assert a.get("/me/pc").json()["parts"] == {"cpu": "가" * 120}                       # 거절된 요청은 아무것도 바꾸지 않았다


# ── C-2 사용자별 JSON 문서 ───────────────────────────────────────────────────────────
def test_documents_hold_any_json_and_are_per_user(alice, bob):
    a, b = alice, bob
    workspace = {"state": {"stage": 2, "currentPlan": None, "conditions": {"intent": "게임", "performance": "", "quiet": "조용"}},
                 "checkDraft": {"question": "이 견적 괜찮아?", "budget": "150", "rows": [{"type": "CPU", "name": "7600", "price": 221750}]},
                 "한글키": [1, 2.5, None, True, "문자열"]}
    assert a.put("/me/data/workspace", json={"value": workspace}).status_code == 200
    got = a.get("/me/data/workspace").json()
    assert got["key"] == "workspace" and got["value"] == workspace and got["updated_at"]            # 모양 그대로(한글·null·실수 포함)
    for key, value in (("check-sessions", {"d1": {"createdAt": "2026-10-14T00:00:00Z", "comparisonId": "c1"}}), ("sidepanel.groups", ["a", "b"]),
                       ("plain-text", "그냥 문자열"), ("number", 42)):
        assert a.put(f"/me/data/{key}", json={"value": value}).status_code == 200
        assert a.get(f"/me/data/{key}").json()["value"] == value
    listing = a.get("/me/data").json()
    assert [i["key"] for i in listing["items"]] == ["check-sessions", "number", "plain-text", "sidepanel.groups", "workspace"]
    assert all(i["size_bytes"] > 0 and i["updated_at"] for i in listing["items"])
    assert listing["limits"] == {"max_keys": 50, "max_bytes_per_document": 262144, "max_depth": 32}
    assert b.get("/me/data/workspace").status_code == 404 and b.get("/me/data").json()["items"] == []     # 다른 사용자에게는 없다
    newer = a.put("/me/data/workspace", json={"value": {"state": 2}}).json()
    assert a.get("/me/data/workspace").json()["value"] == {"state": 2} and newer["updated_at"] >= got["updated_at"]   # 통째로 교체
    assert a.delete("/me/data/number").status_code == 204 and a.delete("/me/data/number").status_code == 204
    assert a.get("/me/data/number").status_code == 404


def test_document_limits(alice):
    a = alice
    for key in ("Upper", "한글", "has space", "-leading", "a" * 65, "slash/ed"):
        r = a.put(f"/me/data/{key}", json={"value": 1}) if "/" not in key else a.put("/me/data/slash%2Fed", json={"value": 1})
        assert r.status_code in (404, 405, 422), key                                     # 키 모양 위반(슬래시는 경로가 갈려 404·405)
    assert a.put("/me/data/Upper", json={"value": 1}).json()["error"]["code"] == "invalid_key"
    assert a.get("/me/data/Upper").status_code == 422
    big = a.put("/me/data/big", json={"value": {"text": "가" * 90000}})                      # 한글은 3바이트라 270KB 가 넘는다
    assert big.status_code == 422 and big.json()["error"]["code"] == "document_too_large"
    assert a.put("/me/data/ok-size", json={"value": {"text": "a" * 200000}}).status_code == 200
    deep: object = 1
    for _ in range(40):
        deep = {"n": deep}
    r = a.put("/me/data/deep", json={"value": deep})
    assert r.status_code == 422 and r.json()["error"]["code"] == "document_too_deep"
    assert a.put("/me/data/shallow", json={"value": {"a": {"b": {"c": [1, [2, [3]]]}}}}).status_code == 200
    assert a.put("/me/data/no-value", json={}).status_code == 422                            # value 가 있어야 한다


def test_document_count_limit_applies_to_new_keys_only(alice, monkeypatch):
    from src.services import me_service
    monkeypatch.setattr(me_service, "DATA_MAX_KEYS", 3)
    a = alice
    for i in range(3):
        assert a.put(f"/me/data/k{i}", json={"value": i}).status_code == 200
    r = a.put("/me/data/k3", json={"value": 3})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_documents"
    assert a.put("/me/data/k1", json={"value": "바뀜"}).status_code == 200                      # 있는 키를 고치는 것은 된다
    assert a.delete("/me/data/k0").status_code == 204
    assert a.put("/me/data/k3", json={"value": 3}).status_code == 200                         # 지우면 다시 넣을 수 있다


def test_write_rate_limit(alice, monkeypatch):
    from src.routers import me as me_router
    monkeypatch.setattr(me_router, "ME_WRITE_LIMIT_PER_MIN", 4)
    a = alice
    codes = [a.put("/me/data/autosave", json={"value": i}).status_code for i in range(6)]
    assert codes == [200, 200, 200, 200, 429, 429]
    assert a.get("/me/data/autosave").status_code == 200                                       # 읽기는 한도에 걸리지 않는다


# ── C-2 견적서별 부가 정보 ───────────────────────────────────────────────────────────
def _new_list(c: TestClient) -> str:
    return c.post("/session").json()["list_id"]


SETUP_EXTRAS = {
    "mode": "new", "budget": 1500000,
    "conditions": {"intent": "영상 편집 겸 게임", "performance": "QHD 144Hz", "quiet": "밤에 써서 조용했으면"},
    "checkSnapshot": {"question": "호환 점검", "budget": "150", "rows": [{"type": "CPU", "name": "라이젠 5 7600", "price": "221,750"}]},
    "desk": {"deskUnlocked": True, "deskWidth": 1600, "deskDepth": 800, "deskHeight": 750},
    "checkDraft": {"question": "", "budget": "", "rows": []},
}


def test_plan_extras_hold_everything_the_browser_kept(alice, bob):
    a, b = alice, bob
    list_id = _new_list(a)
    assert a.get(f"/lists/{list_id}/extras").json() == {"list_id": list_id, "extras": None, "updated_at": None}      # 저장한 적이 없으면 null
    saved = a.put(f"/lists/{list_id}/extras", json={"extras": SETUP_EXTRAS})
    assert saved.status_code == 200 and saved.json()["extras"] == SETUP_EXTRAS
    again = a.get(f"/lists/{list_id}/extras").json()
    assert again["extras"] == SETUP_EXTRAS and again["updated_at"] and again["list_id"] == list_id
    a.put(f"/lists/{list_id}/extras", json={"extras": {"desk": {"deskWidth": 1200}}})                              # 통째로 교체
    assert a.get(f"/lists/{list_id}/extras").json()["extras"] == {"desk": {"deskWidth": 1200}}
    assert b.get(f"/lists/{list_id}/extras").status_code == 404                                                    # 남의 목록
    assert b.put(f"/lists/{list_id}/extras", json={"extras": {"x": 1}}).status_code == 404
    assert b.delete(f"/lists/{list_id}/extras").status_code == 404
    assert a.get(f"/lists/{uuid4()}/extras").status_code == 404
    assert a.delete(f"/lists/{list_id}/extras").status_code == 204 and a.delete(f"/lists/{list_id}/extras").status_code == 204
    assert a.get(f"/lists/{list_id}/extras").json()["extras"] is None


def test_all_extras_for_the_sidebar_comes_in_one_call(alice, bob):
    a, b = alice, bob
    first, second = _new_list(a), _new_list(a)
    other = _new_list(b)
    a.put(f"/lists/{first}/extras", json={"extras": {"mode": "new"}})
    a.put(f"/lists/{second}/extras", json={"extras": {"mode": "upgrade"}})
    b.put(f"/lists/{other}/extras", json={"extras": {"mode": "new"}})
    items = a.get("/lists/extras").json()["items"]
    assert set(items) == {first, second} and items[first]["extras"] == {"mode": "new"} and items[second]["extras"] == {"mode": "upgrade"}
    assert list(items)[0] == second                                                                                # 최근 수정순
    assert set(b.get("/lists/extras").json()["items"]) == {other}
    a.delete(f"/lists/{first}")                                                                                    # 목록을 지우면 부가 정보도 안 보인다
    assert set(a.get("/lists/extras").json()["items"]) == {second}


def test_extras_must_be_an_object_and_respect_limits(alice):
    a = alice
    list_id = _new_list(a)
    assert a.put(f"/lists/{list_id}/extras", json={"extras": [1, 2]}).status_code == 422
    assert a.put(f"/lists/{list_id}/extras", json={"extras": "문자열"}).status_code == 422
    assert a.put(f"/lists/{list_id}/extras", json={}).status_code == 422
    big = a.put(f"/lists/{list_id}/extras", json={"extras": {"text": "가" * 90000}})
    assert big.status_code == 422 and big.json()["error"]["code"] == "document_too_large"
    deep: object = 1
    for _ in range(40):
        deep = {"n": deep}
    assert a.put(f"/lists/{list_id}/extras", json={"extras": deep}).json()["error"]["code"] == "document_too_deep"
    assert a.get(f"/lists/{list_id}/extras").json()["extras"] is None                                              # 거절된 요청은 저장하지 않는다


def test_guest_lists_cannot_get_extras(alice):
    guest = TestClient(app)
    list_id = guest.post("/session").json()["list_id"]
    assert guest.put(f"/lists/{list_id}/extras", json={"extras": {"x": 1}}).status_code == 401           # 게스트는 로그인 뒤에 쓴다
    a = alice
    assert a.put(f"/lists/{list_id}/extras", json={"extras": {"x": 1}}).status_code == 404                # 남이 만든 게스트 목록도 안 된다
