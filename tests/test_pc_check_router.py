"""POST /pc/owned-parts/preview — 라우터 연결·스키마 확인. 판정 자체(ok/warn 갈림)는
tests/test_owned_parts_preview.py가 순수 함수로 이미 촘촘히 본다. 세션·로그인 없이 부른다."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.api import app  # noqa: E402


@pytest.fixture(autouse=True)
def _synthetic_catalog(monkeypatch):
    # DB 연결 여부와 무관하게 항상 같은(합성) 카탈로그로 재현 가능하게 고정한다.
    monkeypatch.setenv("CATALOG_SOURCE", "mock")


client = TestClient(app)


def test_known_model_comes_back_ok_with_the_catalog_name():
    res = client.post("/pc/owned-parts/preview", json={"current_specs": {"CPU": "i5-14400F"}})
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["part"] == "CPU"
    assert rows[0]["state"] == "ok"
    assert "14400F" in rows[0]["matched"]


def test_unknown_model_comes_back_warn_without_being_invented():
    res = client.post("/pc/owned-parts/preview", json={"current_specs": {"GPU": "제가 만든 그래픽카드"}})
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert rows == [{"part": "GPU", "original": "제가 만든 그래픽카드", "matched": "제가 만든 그래픽카드",
                     "matched_note": "확인 가능한 스펙이 없습니다.", "state": "warn"}]


def test_no_login_or_session_required():
    res = client.post("/pc/owned-parts/preview", json={"current_specs": {}})
    assert res.status_code == 200
    assert res.json() == {"rows": []}


def test_extra_or_missing_current_specs_do_not_error(monkeypatch):
    assert client.post("/pc/owned-parts/preview", json={}).status_code == 200


def test_free_text_is_extracted_by_the_rule_fallback_when_no_llm_agent_is_on():
    # 이 테스트 환경은 MOCK_MODE=1(기본)이라 spec_extraction_agent.available()이 False다 —
    # 그래서 규칙 기반 파서(key: value 줄)로 떨어진다. LLM 경로 자체는 test_spec_extraction_agent.py에서 본다.
    text = "CPU: i5-14400F\nGPU: 제가 만든 그래픽카드\n"
    res = client.post("/pc/owned-parts/preview", json={"text": text})
    assert res.status_code == 200
    rows = {r["part"]: r for r in res.json()["rows"]}
    assert rows["CPU"]["state"] == "ok"
    assert rows["GPU"]["state"] == "warn"


def test_explicit_current_specs_win_over_text_extraction_for_the_same_slot():
    res = client.post("/pc/owned-parts/preview", json={
        "current_specs": {"CPU": "i5-14400F"}, "text": "CPU: 다른 값\nGPU: RTX 4070 SUPER\n",
    })
    rows = {r["part"]: r for r in res.json()["rows"]}
    assert rows["CPU"]["original"] == "i5-14400F"     # text의 "다른 값"에 덮이지 않는다
    assert rows["GPU"]["original"] == "RTX 4070 SUPER"


def test_free_flowing_text_with_no_recognisable_lines_yields_no_rows():
    res = client.post("/pc/owned-parts/preview", json={"text": "라이젠 7800X3D에 4070 SUPER 얹었어요"})
    assert res.status_code == 200
    assert res.json() == {"rows": []}


def test_text_over_the_length_limit_is_rejected():
    res = client.post("/pc/owned-parts/preview", json={"text": "x" * 20_001})
    assert res.status_code == 422


# ── 이미지(스크린샷) — 규칙 기반 대안이 없어 꺼져 있으면 조용히 넘기지 않고 503으로 알린다 ──────
def test_image_without_the_extraction_agent_on_is_a_clear_503_not_a_silent_empty_result():
    # 이 테스트 환경은 기본 MOCK_MODE=1이라 spec_extraction_agent.available()이 False다.
    res = client.post("/pc/owned-parts/preview", json={"image_data_url": "data:image/png;base64,AAAA"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "image_extraction_unavailable"


def test_malformed_image_data_url_is_rejected_before_calling_any_agent():
    res = client.post("/pc/owned-parts/preview", json={"image_data_url": "not-a-data-url"})
    assert res.status_code == 422
    res2 = client.post("/pc/owned-parts/preview", json={"image_data_url": "data:application/pdf;base64,AAAA"})
    assert res2.status_code == 422


def test_oversized_image_is_rejected():
    res = client.post("/pc/owned-parts/preview", json={"image_data_url": "data:image/png;base64," + "A" * 7_000_001})
    assert res.status_code == 422


def test_image_extraction_success_path_and_explicit_current_specs_still_win(monkeypatch):
    import src.routers.pc_check as pc_check

    monkeypatch.setattr(pc_check.spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(pc_check.spec_extraction_agent, "extract_from_image",
                        lambda url: {"CPU": "라이젠 7 7800X3D", "GPU": "RTX 4070 SUPER"})
    res = client.post("/pc/owned-parts/preview", json={
        "current_specs": {"CPU": "i5-14400F"}, "image_data_url": "data:image/png;base64,AAAA",
    })
    assert res.status_code == 200
    rows = {r["part"]: r for r in res.json()["rows"]}
    assert rows["CPU"]["original"] == "i5-14400F"    # 명시값이 이미지 추출값을 덮지 않는다
    assert rows["GPU"]["original"] == "RTX 4070 SUPER"


def test_image_extraction_failure_is_503_not_a_silent_empty_result(monkeypatch):
    import src.routers.pc_check as pc_check

    def boom(url):
        raise RuntimeError("vision call failed")

    monkeypatch.setattr(pc_check.spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(pc_check.spec_extraction_agent, "extract_from_image", boom)
    res = client.post("/pc/owned-parts/preview", json={"image_data_url": "data:image/png;base64,AAAA"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "image_extraction_failed"
