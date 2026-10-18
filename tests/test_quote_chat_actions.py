"""받은 견적 점검 채팅 동작(재기획 6단계) — 요청 말투만 동작하고, 질문은 동작하지 않는다. 실제(DB) 카탈로그를 쓴다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")


# ── 해석(DB 없음) ──────────────────────────────────────────────────────────────
def _parse(text, analyzed=True, replaced=()):
    from src.services import quote_chat_actions
    return quote_chat_actions.parse(text, analyzed=analyzed, replaced=set(replaced))


@pytest.mark.parametrize("text", [
    "GPU를 RTX 5070으로 바꾸면 어때?", "교체 목록에 담으면 얼마나 비싸져?", "GPU 대안 알려줘", "RTX 4070이랑 비교해줘",
    "이 견적으로 사이버펑크 돌아가?", "예산이 얼마가 적당해?", "다시 분석하면 달라져?", "호환은 괜찮아?",
])
def test_questions_are_never_actions(text):
    assert _parse(text) is None


@pytest.mark.parametrize("text,kind", [
    ("다시 분석해줘", "reanalyze"), ("재분석 해 주세요", "reanalyze"),
    ("GPU 교체 목록에 담아줘", "add"), ("GPU를 RTX 5070 Ti로 바꿔줘", "add"),
    ("GPU 교체에서 빼줘", "remove"), ("교체 목록 전부 비워줘", "remove_all"),
    ("총 예산 150만원으로 바꿔줘", "condition"), ("용도를 게임으로 바꿔줘", "condition"), ("해상도 QHD로 바꿔줘", "condition"),
    ("우선순위 가성비로 바꿔줘", "condition"), ("CPU 정보 찾아줘", "lookup"), ("CPU를 Ryzen 5 7500F로 정해줘", "fix"),
])
def test_requests_become_actions(text, kind):
    assert _parse(text)["kind"] == kind


def test_before_analysis_a_swap_request_fixes_the_reading_and_after_it_adds_a_replacement():
    assert _parse("GPU를 RTX 5070 Ti로 바꿔줘", analyzed=False)["kind"] == "fix"
    assert _parse("GPU를 RTX 5070 Ti로 바꿔줘", analyzed=True)["kind"] == "add"


def test_condition_values_are_parsed_into_the_patch():
    assert _parse("교체 예산 30만원으로 해줘") is None or "replace_budget" not in (_parse("교체 예산 30만원으로 해줘") or {}).get("patch", {})   # 교체 예산은 없다
    assert _parse("용도를 사무로 바꿔줘")["patch"] == {"purpose": "office"}
    assert _parse("해상도 4K로 바꿔줘")["patch"] == {"resolution": "4K"}
    assert _parse("우선순위를 저소음으로 바꿔줘")["patch"] == {"priority": "quiet"}
    assert _parse("총 예산 150만원으로 바꿔줘")["patch"] == {"budget_max": 1_500_000}


# ── API 흐름 ───────────────────────────────────────────────────────────────────
pytestmark_db = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]
if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.engine.stage3_0_candidates import load_pc_catalog

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _env():
    if DSN:
        ratelimit.reset_all()
    yield
    if DSN:
        ratelimit.reset_all()


@pytest.fixture(scope="module")
def catalog():
    return load_pc_catalog(lambda _msg: None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _weakest_gpu(catalog):
    return min((c for c in catalog["GPU"] if c.product_id and c.specs.get("perf_tier") is not None), key=lambda c: c.specs["perf_tier"])


def _draft(client, monkeypatch, catalog):
    gpu = _weakest_gpu(catalog)
    items = [{"category": "GPU", "raw_text": gpu.name}]
    for slot in ("CPU", "RAM", "메인보드", "저장장치", "파워"):
        cand = min((c for c in catalog[slot] if c.product_id and c.price), key=lambda c: c.price)
        items.append({"category": slot, "raw_text": cand.name})
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: items)
    r = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))], data={"conditions": '{"purpose":"game","resolution":"4K"}'})
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, draft, text):
    r = client.post(f"/pc/reviews/{draft['draft_id']}/messages", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_before_analysis_questions_get_a_notice_but_conditions_can_be_changed_by_chat(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog)
    notice = _say(client, draft, "호환은 어때?")
    assert "분석" in notice["reply"] and notice["action"] is None
    done = _say(client, draft, "해상도 QHD로 바꿔줘")
    assert done["action"]["kind"] == "set_condition" and "QHD" in done["reply"]
    assert client.get(f"/pc/review-drafts/{draft['draft_id']}").json()["conditions"]["resolution"] == "QHD_165"


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_chat_can_add_undo_and_remove_a_replacement(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    assert client.post(f"{base}/analysis").status_code == 200
    added = _say(client, draft, "GPU 교체 목록에 담아줘")
    assert added["action"]["kind"] == "add_replacement" and "교체 목록에 담았어요" in added["reply"] and "호환 문제" in added["reply"], added
    state = client.get(f"{base}/replacements").json()
    assert [r["slot"] for r in state["replacements"]] == ["GPU"]
    assert added["action"]["undo"] == {"kind": "remove_replacement", "slot": "GPU"}
    removed = _say(client, draft, "GPU 교체에서 빼줘")
    assert removed["action"]["kind"] == "remove_replacement" and client.get(f"{base}/replacements").json()["replacements"] == []
    assert removed["action"]["undo"]["kind"] == "restore_replacements"
    nothing = _say(client, draft, "GPU 교체에서 빼줘")
    assert nothing["action"] is None and "없어요" in nothing["reply"]


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_chat_adds_a_named_product_and_refuses_one_that_breaks_compatibility(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    assert client.post(f"{base}/analysis").status_code == 200
    target = next(t for t in client.get(f"{base}/replacement-targets").json()["targets"] if t["slot"] == "GPU")
    name = target["candidates"][0]["name"]
    added = _say(client, draft, f"GPU를 {name}으로 바꿔줘")
    assert added["action"] and name in added["reply"], added
    assert client.get(f"{base}/replacements").json()["replacements"][0]["candidate"]["name"] == name
    unknown = _say(client, draft, "GPU를 RTX 9999 Ti로 바꿔줘")
    assert unknown["action"] is None or unknown["action"]["kind"] != "add_replacement" or "RTX 9999" not in unknown["reply"]


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_chat_reanalyze_and_a_stranger_cannot_act(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    assert client.post(f"{base}/analysis").status_code == 200
    _say(client, draft, "해상도 QHD로 바꿔줘")
    assert client.get(base).json()["analysis_stale"] is True
    again = _say(client, draft, "다시 분석해줘")
    assert again["action"]["kind"] == "reanalyze" and "호환 통과" in again["reply"]
    assert client.get(base).json()["analysis_stale"] is False
    with TestClient(app) as stranger:
        r = stranger.post(f"/pc/reviews/{draft['draft_id']}/messages", json={"text": "해상도 4K로 바꿔줘"})
        assert r.status_code == 404
    assert client.get(base).json()["conditions"].get("resolution") != "4K"


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_chat_asks_before_a_paid_lookup_and_searches_only_after_consent(client, monkeypatch, catalog):
    from src.agent.conditions_agent import SEARCH_PERMISSION_MARKER
    from src.services import live_spec_lookup
    from src.services.live_spec_lookup import LiveSpecLookupResult

    gpu = _weakest_gpu(catalog)
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image",
                        lambda _url: [{"category": "GPU", "raw_text": gpu.name}, {"category": "CPU", "raw_text": "정체불명 프로세서 ZX-1"}])
    draft = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))]).json()
    calls: list[str] = []
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    monkeypatch.setattr(live_spec_lookup, "lookup", lambda conn, text, **kw: calls.append(text) or LiveSpecLookupResult.model_validate(
        {"relevant": True, "supported_fields": {"socket": "AM5"}, "source_url": "https://example.com/zx"}))
    asked = _say(client, draft, "CPU 정보 찾아줘")
    assert SEARCH_PERMISSION_MARKER in asked["reply"] and asked["action"] is None and calls == []          # 묻기만 하고 검색하지 않는다
    done = _say(client, draft, "네")
    assert calls == ["정체불명 프로세서 ZX-1"] and "socket=AM5" in done["reply"]
    again = _say(client, draft, "네")                                                                    # 한 번 동의로 두 번 검색하지 않는다
    assert calls == ["정체불명 프로세서 ZX-1"] and "socket=AM5" not in again["reply"]


