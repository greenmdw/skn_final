"""받은 견적 vs 저장 견적 비교(BE-09)와 그 비교에 대한 질문(BE-10·11·12) — 시각 자료·가이드·같은 질문 재사용·이력 복원.

저장 견적(확정 견적서)은 가짜 리포트로 바꿔 끼운다 — 확정까지의 전체 흐름이 아니라 비교·질문 로직을 본다."""
from __future__ import annotations

import base64
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import quote_review_agent, spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.engine.stage3_0_candidates import load_pc_catalog
    from src.services import quote_chat_service, quote_comparison_service as qcs

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    ratelimit.reset_all()
    monkeypatch.setattr(quote_review_agent, "available", lambda: False)       # 규칙 경로 — LLM 없이 사실 문장
    yield
    ratelimit.reset_all()


@pytest.fixture(scope="module")
def catalog():
    return load_pc_catalog(lambda _msg: None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _pick(catalog, category, n=0):
    """견적 글에 이름만 적어도 **하나로 확정**되는 제품(같은 이름의 변형이 여럿이면 ambiguous라 제품 ID가 없다) — n번째."""
    from src.services import quote_draft_service

    pool = sorted((c for c in catalog[category] if c.product_id and c.price), key=lambda c: c.price)
    sure = [c for c in pool
            if (it := quote_draft_service._make_item(category, c.name, "s", catalog))["match_status"] == "confirmed"
            and it["matched_product_id"] == c.product_id]
    return sure[n]


def _report(catalog, picks: dict):
    """저장 견적(확정 리포트) 모양의 가짜 — slot·product(product_key,name,image_url)·단가·수량."""
    return {"revision_no": 1, "name": "저장한 견적", "items": [
        {"slot": slot, "product": {"product_key": c.product_key, "name": c.name, "image_url": None}, "price": c.price, "qty": 1}
        for slot, c in picks.items()]}


@pytest.fixture()
def setup(client, monkeypatch, catalog):
    """받은 견적(GPU 하나·CPU 하나, 가격 있음)을 분석하고 저장 견적(다른 GPU·같은 CPU)과 비교한 상태."""
    rx_gpu, saved_gpu, cpu = _pick(catalog, "GPU", 0), _pick(catalog, "GPU", 5), _pick(catalog, "CPU", 3)
    items = [{"category": "GPU", "raw_text": f"{rx_gpu.name} {rx_gpu.price + 10000:,}원"},
             {"category": "CPU", "raw_text": f"{cpu.name} {cpu.price:,}원"}]
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: items)
    draft = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))]).json()
    list_id = draft["draft_id"]
    assert client.post(f"/pc/review-drafts/{list_id}/analysis").status_code == 200
    monkeypatch.setattr(qcs.list_service, "get_report", lambda conn, lid, principal, no=None: _report(catalog, {"GPU": saved_gpu, "CPU": cpu}))
    r = client.post(f"/pc/reviews/{list_id}/saved-comparisons", json={"saved_list_id": "00000000-0000-0000-0000-000000000001"})
    assert r.status_code == 201, r.text
    return {"list_id": list_id, "comparison": r.json(), "rx_gpu": rx_gpu, "saved_gpu": saved_gpu, "cpu": cpu}


def _ask(client, setup, text, **extra):
    body = {"text": text, "context": {"type": "saved_quote_comparison", "comparison_id": setup["comparison"]["comparison_id"]}, **extra}
    return client.post(f"/pc/reviews/{setup['list_id']}/messages", json=body)


# ── BE-09 ────────────────────────────────────────────────────────────────────

def test_build_comparison_uses_product_keys_quantities_and_line_totals():
    rx = {"GPU": {"product_key": "a", "name": "A", "line_total": 400000, "quantity": 1},
          "CPU": {"product_key": "c", "name": "C", "line_total": 200000, "quantity": 1},
          "RAM": {"product_key": None, "name": "R", "line_total": None, "quantity": 2}}
    sv = {"GPU": {"product_key": "b", "name": "B", "line_total": 450000, "quantity": 1},
          "CPU": {"product_key": "c", "name": "C", "line_total": 200000, "quantity": 1},
          "케이스": {"product_key": "k", "name": "K", "line_total": 60000, "quantity": 1}}
    out = qcs.build_comparison(rx, sv)
    rows = {r["category"]: r for r in out["rows"]}
    assert rows["CPU"]["same_product"] is True and rows["GPU"]["same_product"] is False
    assert rows["GPU"]["price_diff"] == 50000 and rows["CPU"]["price_diff"] == 0
    assert rows["RAM"]["price_diff"] is None and rows["케이스"]["received"] is None       # 한쪽에만 있는 부품도 행으로 남는다
    assert out["received_total"] == 600000 and out["saved_total"] == 710000          # 가격이 있는 줄의 합(참고)
    assert out["comparable_categories"] == ["CPU", "GPU"] and out["total_diff"] == 50000      # 차이는 양쪽에 가격이 있는 부품만
    assert out["excluded_received_categories"] == ["RAM"]
    assert out["brief_summary"]["changed_count"] == 3 and out["brief_summary"]["largest_price_difference_category"] == "GPU"
    assert "다릅니다" in out["brief_summary"]["text"]


def test_saved_comparison_is_computed_by_the_server_and_can_be_read_back(client, setup):
    comp = setup["comparison"]
    rows = {r["category"]: r for r in comp["rows"]}
    assert rows["CPU"]["same_product"] is True                                    # 같은 제품은 제품 키로 판정
    assert rows["GPU"]["same_product"] is False
    assert rows["GPU"]["received"]["product_id"] == setup["rx_gpu"].product_id
    assert rows["GPU"]["saved"]["product_id"] == setup["saved_gpu"].product_id
    assert rows["GPU"]["price_diff"] == setup["saved_gpu"].price - (setup["rx_gpu"].price + 10000)
    assert comp["brief_summary"]["text"] and comp["computed_at"]
    again = client.get(f"/pc/reviews/{setup['list_id']}/saved-comparisons/{comp['comparison_id']}")
    assert again.status_code == 200 and again.json()["total_diff"] == comp["total_diff"]


def test_comparison_needs_an_analysed_review_and_an_owner(client, monkeypatch, setup, catalog):
    assert client.get(f"/pc/reviews/{setup['list_id']}/saved-comparisons/00000000-0000-0000-0000-000000000009").status_code == 404
    with TestClient(app) as stranger:
        ratelimit.reset_all()
        r = stranger.post(f"/pc/reviews/{setup['list_id']}/saved-comparisons", json={"saved_list_id": "00000000-0000-0000-0000-000000000001"})
        assert r.status_code == 404
        assert stranger.get(f"/pc/reviews/{setup['list_id']}/saved-comparisons/{setup['comparison']['comparison_id']}").status_code == 404


# ── BE-10: 질문별 시각 자료 ───────────────────────────────────────────────────

def test_a_price_question_returns_a_price_table_and_no_guides(client, setup, monkeypatch):
    monkeypatch.setattr("src.rag.care_guides.search_care_guide", lambda *a, **k: pytest.fail("가격 질문에 가이드를 찾으면 안 된다"))
    body = _ask(client, setup, "가격 차이가 얼마야?").json()
    assert body["display_target"] == "saved_comparison_explanation" and body["guide_refs"] == []
    assert [v["type"] for v in body["visuals"]] == ["table"]
    assert body["visuals"][0]["title"] == "가격 비교" and len(body["visuals"][0]["rows"]) == 2
    assert "저장 견적 비교" in body["evidence"] and body["message_id"] and body["answer_id"] and body["created_at"]


def test_a_gpu_question_returns_only_gpu_cards_and_table(client, setup):
    body = _ask(client, setup, "GPU 둘 중 뭐가 더 비싸?").json()
    cards = [v for v in body["visuals"] if v["type"] == "product_comparison"]
    assert len(cards) == 1 and cards[0]["category"] == "GPU"
    assert [c["side"] for c in cards[0]["items"]] == ["received", "saved"]
    assert {c["product_id"] for c in cards[0]["items"]} == {setup["rx_gpu"].product_id, setup["saved_gpu"].product_id}
    assert all(v.get("category") in (None, "GPU") for v in body["visuals"])           # CPU 자료는 섞이지 않는다
    assert not any("CPU" == v.get("category") for v in body["visuals"])


def test_cpu_and_gpu_in_one_question_give_separate_objects_per_category(client, setup):
    body = _ask(client, setup, "CPU랑 GPU 가격이 어때?").json()
    cards = {v["category"] for v in body["visuals"] if v["type"] == "product_comparison"}
    assert cards == {"CPU", "GPU"}
    assert sum(v["type"] == "product_comparison" for v in body["visuals"]) == 2


def test_a_compat_question_returns_compat_items_and_the_right_slot_guide(client, setup, monkeypatch):
    calls = []

    def fake_search(query, k=1, slot=None, kind=None):
        calls.append((slot, kind))
        return [{"id": f"{slot}-{kind}", "kind": kind, "text": "가이드 문장", "score": 0.87}]

    monkeypatch.setattr("src.rag.care_guides.search_care_guide", fake_search)
    body = _ask(client, setup, "GPU 전력이 파워로 충분해?").json()
    assert calls[0] == ("GPU", "care") and all(kind == "care" for _slot, kind in calls)    # 구매 전 확인은 care, 언급한 슬롯만
    assert {slot for slot, _kind in calls} == {"GPU", "파워"}                                 # 질문에 나온 두 부품군
    assert {g["slot"] for g in body["guide_refs"]} == {"GPU", "파워"} and all(g["kind"] == "care" for g in body["guide_refs"])
    compat = [v for v in body["visuals"] if v["type"] == "compatibility_check"]
    assert compat and compat[0]["items"] and {i["side"] for i in compat[0]["items"]} <= {"received", "saved"}


def test_install_guide_only_when_install_is_asked(client, setup, monkeypatch):
    calls = []
    monkeypatch.setattr("src.rag.care_guides.search_care_guide",
                        lambda q, k=1, slot=None, kind=None: calls.append((slot, kind)) or [])
    _ask(client, setup, "GPU 설치할 때 주의할 점이 있어?")
    assert calls == [("GPU", "install")]


def test_unknown_comparison_is_404_with_its_code(client, setup):
    r = client.post(f"/pc/reviews/{setup['list_id']}/messages", json={
        "text": "가격은?", "context": {"type": "saved_quote_comparison", "comparison_id": "00000000-0000-0000-0000-000000000009"}})
    assert r.status_code == 404 and r.json()["error"]["code"] == "COMPARISON_NOT_FOUND"


def test_a_question_without_context_still_works_as_before(client, setup):
    r = client.post(f"/pc/reviews/{setup['list_id']}/messages", json={"text": "호환은 문제 없어?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_target"] == "chat" and body["visuals"] == [] and body["guide_refs"] == [] and body["reply"]


# ── BE-12: 이력 복원·같은 질문 ────────────────────────────────────────────────

def test_the_same_question_reuses_the_answer_without_calling_the_model_again(client, setup, monkeypatch):
    runs = []

    class Turn:
        reply, evidence, trace = "모델이 한 답", ["저장 견적 비교"], []

    monkeypatch.setattr(quote_review_agent, "available", lambda: True)
    monkeypatch.setattr(quote_review_agent, "run_turn", lambda *a, **k: runs.append(1) or Turn())
    first = _ask(client, setup, "GPU 가격 차이가 얼마야?").json()
    second = _ask(client, setup, "  gpu   가격 차이가 얼마야??  ").json()           # 공백·대소문자·문장 끝 부호가 달라도 같은 질문
    assert len(runs) == 1                                                            # 두 번째는 모델을 부르지 않는다
    assert second["duplicate_of"] == first["answer_id"] and second["answer_id"] != first["answer_id"]
    assert second["reply"] == first["reply"] and second["visuals"] == first["visuals"] and second["guide_refs"] == first["guide_refs"]
    third = _ask(client, setup, "CPU 가격 차이가 얼마야?").json()                   # 다른 질문은 새로 답한다
    assert third["duplicate_of"] is None and len(runs) == 2


def test_a_resent_client_message_id_returns_the_stored_answer(client, setup):
    first = _ask(client, setup, "GPU 가격은?", client_message_id="front-uuid-1").json()
    again = _ask(client, setup, "GPU 가격은?", client_message_id="front-uuid-1").json()
    assert again["message_id"] == first["message_id"] and again["answer_id"] == first["answer_id"]
    history = client.get(f"/pc/reviews/{setup['list_id']}/messages").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]                     # 재전송은 이력을 늘리지 않는다


def test_history_restores_per_question_visuals_guides_and_comparison(client, setup):
    first = _ask(client, setup, "GPU 가격 차이가 얼마야?").json()
    messages = client.get(f"/pc/reviews/{setup['list_id']}/messages").json()["messages"]
    answer = next(m for m in messages if m["role"] == "assistant")
    assert answer["answer_id"] == first["answer_id"] and answer["comparison_id"] == setup["comparison"]["comparison_id"]
    assert answer["visuals"] == first["visuals"] and answer["display_target"] == "saved_comparison_explanation"
    question = next(m for m in messages if m["role"] == "user")
    assert question["comparison_id"] == setup["comparison"]["comparison_id"]


def test_normalize_question_rules():
    n = qcs.normalize_question
    assert n("  GPU   파워가 충분해?! ") == "gpu 파워가 충분해"
    assert n("Hello。") == "hello" and n("a？！") == "a"
    assert n("가격?") == n("가격")


def test_total_difference_is_not_claimed_when_one_side_has_no_prices():
    """한쪽 견적에 가격이 하나도 없으면 "저장 견적이 179만 원 더 저렴"처럼 말하면 안 된다(사진 시험에서 실제로 나왔던 문구)."""
    rx = {"CPU": {"product_key": "a", "name": "A", "line_total": 316000, "quantity": 1},
          "GPU": {"product_key": "g", "name": "G", "line_total": 449000, "quantity": 1}}
    sv = {"CPU": {"product_key": "b", "name": "B", "line_total": None, "quantity": 1},
          "GPU": {"product_key": "h", "name": "H", "line_total": None, "quantity": 1}}
    out = qcs.build_comparison(rx, sv)
    assert out["comparable_categories"] == [] and out["total_diff"] == 0
    assert "총액 차이는 비교하지 않았습니다" in out["brief_summary"]["text"]
    assert "더 저렴" not in out["brief_summary"]["text"] and "더 비쌉" not in out["brief_summary"]["text"]


def test_summary_names_the_basis_when_only_some_parts_are_comparable():
    rx = {"CPU": {"product_key": "a", "name": "A", "line_total": 300000, "quantity": 1},
          "GPU": {"product_key": "g", "name": "G", "line_total": 400000, "quantity": 1}}
    sv = {"CPU": {"product_key": "b", "name": "B", "line_total": 320000, "quantity": 1},
          "GPU": {"product_key": "h", "name": "H", "line_total": None, "quantity": 1}}
    text = qcs.build_comparison(rx, sv)["brief_summary"]["text"]
    assert "가격이 양쪽에 있는 1개 부품 기준" in text and "20,000원" in text
