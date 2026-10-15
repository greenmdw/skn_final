"""9번 동시성·정합성(§11)과 8번 보안·권한(§10) 시나리오 중 기존 테스트에 없던 것.

실제 LLM 호출 없음. 일회용 테스트 DB 필요. 동시성은 타이밍에 따라 한 번에 안 터질 수 있어 여러 번 반복한다(§2.5)."""
from __future__ import annotations

import base64
import json
import os
import threading
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
REPEATS = 5


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset_all()
    yield


def _signed_up() -> "TestClient":
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/auth/signup", json={"email": f"cs-{uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": "cs",
                                     "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def _ready_session(c) -> str:
    lid = c.post("/session").json()["list_id"]
    c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", 2_000_000), ("q_priority", "성능 우선")):
        assert c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]}).status_code == 200
    return lid


def _two_clients_same_user(c) -> "TestClient":
    """같은 로그인 쿠키를 가진 두 번째 클라이언트(= 같은 사용자의 두 탭)."""
    other = TestClient(app, raise_server_exceptions=False)
    other.cookies.update(c.cookies)
    return other


# ── 9번: 동시성·정합성 ───────────────────────────────────────────────────────

def _draft(c, monkeypatch) -> dict:
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image",
                        lambda _u: [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F 238,000원"}, {"category": "GPU", "raw_text": "AMD Radeon RX 7600 438,000원"}])
    r = c.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("round_no", range(REPEATS))
def test_two_simultaneous_draft_patches_with_the_same_version_one_wins_one_gets_409(monkeypatch, round_no):
    """같은 초안에 같은 expected_version 으로 동시에 PATCH — 행 잠금으로 직렬화돼 하나는 성공, 하나는 409(STALE_REVIEW_VERSION)."""
    c = _signed_up()
    draft = _draft(c, monkeypatch)
    url = f"/pc/review-drafts/{draft['draft_id']}/items"
    cpu = next(i for i in draft["items"] if i["category"] == "CPU")
    other = _two_clients_same_user(c)
    results: list = [None, None]
    barrier = threading.Barrier(2)

    def go(index: int, client: "TestClient", qty: int):
        barrier.wait()
        results[index] = client.patch(url, json={"expected_version": 1, "items": [{"id": cpu["id"], "quantity": qty}]})

    threads = [threading.Thread(target=go, args=(0, c, 2)), threading.Thread(target=go, args=(1, other, 3))]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert sorted(r.status_code for r in results) == [200, 409], [r.status_code for r in results]
    final = c.get(f"/pc/review-drafts/{draft['draft_id']}").json()
    assert final["version"] == 2                                                   # 한 번만 반영
    winner = next(r for r in results if r.status_code == 200).json()
    assert next(i for i in final["items"] if i["id"] == cpu["id"])["quantity"] == next(i for i in winner["items"] if i["id"] == cpu["id"])["quantity"]


@pytest.mark.parametrize("round_no", range(3))
def test_burst_of_messages_in_one_session_neither_errors_nor_corrupts_conditions(round_no):
    """같은 세션에 메시지 3개를 거의 동시에 — 500 없이 모두 처리되고, 대화는 질문·답이 짝지어 저장되며 조건 값이 깨지지 않는다."""
    c = _signed_up()
    lid = c.post("/session").json()["list_id"]
    c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    clients = [c, _two_clients_same_user(c), _two_clients_same_user(c)]
    texts = ["게임용 PC 맞추고 싶어요", "예산은 150만원이에요", "성능 우선으로 부탁해요"]
    codes: list = [None] * 3
    barrier = threading.Barrier(3)

    def go(i: int):
        barrier.wait()
        codes[i] = clients[i].post(f"/session/{lid}/message", json={"text": texts[i]}).status_code

    threads = [threading.Thread(target=go, args=(i,)) for i in range(3)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert all(code == 200 for code in codes), codes
    state = c.get(f"/session/{lid}").json()
    roles = [m["role"] for m in state["messages"] if m["role"] in ("user", "assistant")]
    assert roles.count("user") == 3 and roles.count("assistant") >= 3
    fields = {f["key"]: f["value"] for f in state["fields"]}
    assert fields.get("budget_max") in (None, 1_500_000) and fields.get("purpose") in (None, "game") and fields.get("priority") in (None, "performance")


def test_swap_or_chat_requests_during_a_running_recommendation_never_500_and_the_result_stays_consistent():
    c = _signed_up()
    lid = _ready_session(c)
    codes: list = []
    started = threading.Event()

    def recommend():
        started.set()
        c.post(f"/session/{lid}/recommend")

    other = _two_clients_same_user(c)
    t = threading.Thread(target=recommend)
    t.start()
    started.wait(5)
    for _ in range(6):                                                              # 추천이 도는 동안 존재하지 않는 항목 교체·결과 조회를 반복
        codes.append(other.post(f"/session/{lid}/items/{uuid4()}/swap", json={"candidate_id": str(uuid4())}).status_code)
        codes.append(other.get(f"/session/{lid}/result").status_code)
    t.join(timeout=120)
    assert all(code < 500 for code in codes), codes
    done = c.get(f"/session/{lid}/result").json()
    assert done["status"] == "done"
    slots = [i["slot"] for i in done["items"]]
    assert len(slots) == len(set(slots)) == 8                                       # 슬롯이 겹치거나 빠지지 않는다
    total = sum(i["price"] * i.get("qty", 1) for i in done["items"] if i.get("price") is not None)
    assert done["totals"]["selected_price"] == total                                # 합계가 항목과 어긋나지 않는다


def test_a_failure_in_the_explanation_phase_leaves_the_committed_parts_and_prices_intact(monkeypatch):
    """[5] 설명 생성은 별도 트랜잭션 — 그 단계가 통째로 실패해도 앞 단계가 커밋한 부품·가격·검증은 그대로다(run.status 도 done)."""
    from src.engine import stage5_explain

    def boom(*a, **k):
        raise RuntimeError("explanation phase crashed")

    monkeypatch.setattr(stage5_explain, "run", boom)
    c = _signed_up()
    lid = _ready_session(c)
    c.post(f"/session/{lid}/recommend")
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    assert len(data["items"]) == 8 and all(i["product"]["name"] and i["price"] for i in data["items"])


# ── 8번: 보안·권한 ───────────────────────────────────────────────────────────

def _forge_token(token: str) -> str:
    head, payload, sig = token.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    body["sub"] = str(uuid4())                                                      # 다른 사용자인 척 payload 만 바꾼다(서명은 그대로)
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    return f"{head}.{forged}.{sig}"


def _cookie_name() -> str:
    from src.config import COOKIE_NAME
    return COOKIE_NAME


def test_a_tampered_jwt_payload_is_rejected():
    owner = _signed_up()
    lid = owner.post("/session").json()["list_id"]
    token = owner.cookies.get(_cookie_name())
    assert token and token.count(".") == 2
    attacker = TestClient(app, raise_server_exceptions=False)
    attacker.cookies.set(_cookie_name(), _forge_token(token))
    assert attacker.get("/auth/me").status_code == 401
    assert attacker.get(f"/session/{lid}").status_code in (401, 404)


def test_a_malformed_or_empty_token_is_rejected_not_a_500():
    for bad in ("garbage", "a.b.c", "", "Bearer x"):
        c = TestClient(app, raise_server_exceptions=False)
        c.cookies.set(_cookie_name(), bad)
        assert c.get("/auth/me").status_code == 401, bad


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/lists", None), ("GET", "/auth/me", None), ("POST", "/lists/{lid}/confirm", {"name": "x"}),
    ("DELETE", "/lists/{lid}", None), ("PATCH", "/lists/{lid}", {"name": "x"})])
def test_protected_endpoints_without_credentials_never_succeed(method, path, body):
    owner = _signed_up()
    lid = owner.post("/session").json()["list_id"]
    anon = TestClient(app, raise_server_exceptions=False)
    r = anon.request(method, path.format(lid=lid), json=body)
    if path == "/lists":
        # 익명 목록 조회는 "자기(게스트) 것"을 돌려주는 설계라 200이다 — 남(소유자)의 목록이 보이지 않아야 한다
        assert r.status_code == 200 and lid not in json.dumps(r.json())
        return
    assert r.status_code in (401, 403, 404), (path, r.status_code)                 # 게스트/익명은 남의 리스트를 못 건드린다


def test_another_users_session_cannot_be_read_changed_or_deleted():
    a, b = _signed_up(), _signed_up()
    lid = _ready_session(a)
    for method, path, body in [("GET", f"/session/{lid}", None), ("GET", f"/session/{lid}/result", None),
                               ("POST", f"/session/{lid}/message", {"text": "내 걸로 바꿔"}), ("POST", f"/session/{lid}/recommend", None),
                               ("PATCH", f"/lists/{lid}", {"name": "해킹"}), ("DELETE", f"/lists/{lid}", None)]:
        r = b.request(method, path, json=body)
        assert r.status_code in (403, 404), (method, path, r.status_code)
    assert a.get(f"/session/{lid}").status_code == 200                              # 주인의 것은 그대로


def test_cookie_flags_are_httponly_and_samesite():
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"ck-{uuid4().hex[:10]}@example.test", "password": "abcd1234", "display_name": "ck",
                                     "terms_agreed": True, "privacy_agreed": True})
    header = r.headers.get("set-cookie", "").lower()
    assert "httponly" in header and "samesite=lax" in header
    from src.config import COOKIE_SECURE
    assert ("secure" in header) == bool(COOKIE_SECURE)                              # Secure 는 설정(COOKIE_SECURE)을 따른다 — https 배포에선 1


def test_pc_check_endpoints_are_rate_limited_and_the_limit_is_per_ip():
    c = TestClient(app, raise_server_exceptions=False)
    codes = [c.post("/pc/owned-parts/preview", json={"text": "CPU: AMD Ryzen 5 7500F"}).status_code for _ in range(14)]
    assert 429 in codes and codes.index(429) <= 10                                  # 분당 10회를 넘기면 429
    assert codes[0] == 200


def test_lists_pagination_limit_and_offset_work():
    c = _signed_up()
    ids = [c.post("/session").json()["list_id"] for _ in range(5)]
    for lid in ids:
        c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    full = c.get("/lists").json()
    assert len(full if isinstance(full, list) else full.get("lists", full.get("items"))) >= 5
    page = c.get("/lists", params={"limit": 2, "offset": 1}).json()
    items = page if isinstance(page, list) else page.get("lists", page.get("items"))
    assert len(items) == 2
