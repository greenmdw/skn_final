"""확정할 때 추천 이유가 아직 없으면(만드는 중·실패) 저장된 사실만으로 쓴 규칙 문장을 얼린다.

리포트는 확정 스냅샷(planning.purchase_line.snapshot)만 읽는다 — 빈 문자열을 얼리면 이후에 이유가 채워져도 확정본에는 영영
비어 있다. 부품표를 설명보다 먼저 보여 주면(done 즉시 표시) 이유가 pending 인 채 확정하는 일이 늘어난다. 확정은 이유가
대기 중이어도 막지 않는다. 일회용 DB 가 필요하다(tests/conftest.py 가 자동으로 만든다)."""
from __future__ import annotations

import os

import pytest

from src.services.list_service import _frozen_evidence

DSN = os.getenv("DATABASE_URL")

if DSN:
    import psycopg

    from tests.test_list_history_http import _recommended_list, _signed_up


def _row(reason, **extra) -> dict:
    return {"reason": reason, "slot_label": "그래픽카드", "product_name": "테스트 GPU 5070", "price": 650_000, **extra}


def test_a_stored_reason_is_frozen_as_it_is():
    assert _frozen_evidence(_row("전력 대비 성능이 좋아 골랐어요."), None) == ("전력 대비 성능이 좋아 골랐어요.", "recommendation")


def test_an_empty_reason_becomes_a_rule_sentence_made_of_stored_facts_only():
    for empty in (None, "", "  \n"):
        text, source = _frozen_evidence(_row(empty), None)
        assert source == "rule_fallback"
        assert text == "그래픽카드 테스트 GPU 5070 — 단가 650,000원. AI 추천 이유 없이 확정되어 저장된 정보만 적었습니다."
    # 결과 화면이 계산해 둔 점검 문구(코드가 만든 것)가 있으면 그대로 덧붙이고, 슬롯 라벨은 결과 화면의 것을 우선한다
    view = {"slot_label": "GPU", "checks": {"status": "ready", "text": "사용 가이드: 전원 커넥터 확인 · 이 부품에 걸린 세트 검증 쟁점 없음"}}
    text, source = _frozen_evidence(_row(None), view)
    assert source == "rule_fallback"
    assert text.startswith("GPU 테스트 GPU 5070 — 단가 650,000원.")
    assert text.endswith("구매 전 확인: 사용 가이드: 전원 커넥터 확인 · 이 부품에 걸린 세트 검증 쟁점 없음")
    # 점검 문구가 비면 그 줄은 없다
    assert "구매 전 확인" not in _frozen_evidence(_row(None), {"checks": {"status": "ready", "text": None}})[0]


def _frozen_snapshots(revision_id) -> dict[str, dict]:
    with psycopg.connect(DSN) as conn:
        rows = conn.execute("SELECT snapshot FROM planning.purchase_line WHERE revision_id=%s", (revision_id,)).fetchall()
    return {snapshot["slot"]: snapshot for (snapshot,) in rows}


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_confirm_with_pending_or_failed_reasons_freezes_a_rule_sentence_and_marks_its_source():
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    items = [item for item in data["items"] if item["selected"]]
    pending, failed, *ready = items
    assert ready and all(item["reason"]["status"] == "ready" and item["reason"]["text"] for item in ready)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("UPDATE engine.recommendation_candidate SET reason=NULL, reason_status='pending' WHERE id=%s", (pending["item_id"],))
        conn.execute("UPDATE engine.recommendation_candidate SET reason=NULL, reason_status='failed' WHERE id=%s", (failed["item_id"],))
    shown = {item["item_id"]: item for item in c.get(f"/session/{lid}/result").json()["items"]}
    assert shown[pending["item_id"]]["reason"]["status"] == "pending" and shown[failed["item_id"]]["reason"]["status"] == "failed"

    # 이유가 대기 중이어도 확정은 막지 않는다
    r = c.post(f"/lists/{lid}/confirm", json={"name": "이유 대기 중 확정"})
    assert r.status_code == 200, r.text

    frozen = _frozen_snapshots(revision_id)
    for item in (pending, failed):
        snapshot = frozen[item["slot"]]
        text = snapshot["evidence_text"]
        assert snapshot["evidence_source"] == "rule_fallback"
        assert text.strip(), "빈 문자열을 얼리면 확정본에 이유가 영영 없다"
        # 저장된 사실만: 슬롯 라벨·상품명·단가·결과 화면의 점검 문구
        assert item["slot_label"] in text and item["product"]["name"] in text and f"{item['price']:,}원" in text
        assert shown[item["item_id"]]["checks"]["text"] in text
    for item in ready:
        snapshot = frozen[item["slot"]]
        assert snapshot["evidence_source"] == "recommendation" and snapshot["evidence_text"] == item["reason"]["text"]

    # 리포트는 스냅샷을 그대로 읽는다
    report = c.get(f"/lists/{lid}/report").json()
    by_slot = {line["slot"]: line for line in report["items"]}
    assert all(line["evidence_text"].strip() for line in report["items"])
    assert by_slot[pending["slot"]]["evidence_text"] == frozen[pending["slot"]]["evidence_text"]

    # 뒤늦게 이유가 채워져도 확정본은 그대로다
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("UPDATE engine.recommendation_candidate SET reason=%s, reason_status='ready' WHERE id=%s",
                     ("뒤늦게 도착한 문장", pending["item_id"]))
    again = {line["slot"]: line for line in c.get(f"/lists/{lid}/report").json()["items"]}
    assert again[pending["slot"]]["evidence_text"] == frozen[pending["slot"]]["evidence_text"]
    assert _frozen_snapshots(revision_id)[pending["slot"]]["evidence_source"] == "rule_fallback"


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
def test_confirm_with_every_reason_ready_marks_all_as_recommendation():
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "이유 준비 후 확정"}).status_code == 200

    frozen = _frozen_snapshots(revision_id)
    items = [item for item in data["items"] if item["selected"]]
    assert items and set(frozen) == {item["slot"] for item in items}
    for item in items:
        assert frozen[item["slot"]]["evidence_source"] == "recommendation"
        assert frozen[item["slot"]]["evidence_text"] == item["reason"]["text"]
