"""견적 점검 "확인된 PC 구성" 표 미리보기(preview_current_specs) — 실제 추천 실행(resolve_owned_parts)과
같은 매칭 함수를 쓰는지, 화면이 기대하는 두 상태(ok/warn)로만 나오는지 확인한다."""
from __future__ import annotations

from src.dto import Candidate
from src.engine.owned_parts import preview_current_specs

SLOT_STRUCTURE = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]


def _cand(slot, name, **specs):
    return Candidate(slot=slot, product_key=name, name=name, price=1, specs=specs)


POOL = {
    "CPU": [_cand("CPU", "AMD Ryzen 7 7800X3D", socket="AM5")],
    "메인보드": [_cand("메인보드", "ASUS TUF B650M-PLUS", socket="AM5", mem_type="DDR5")],
}


def test_catalog_match_is_ok_and_uses_the_real_product_name():
    rows = preview_current_specs({"CPU": "Ryzen 7 7800X3D"}, POOL, SLOT_STRUCTURE)
    assert rows == [{"part": "CPU", "original": "Ryzen 7 7800X3D", "matched": "AMD Ryzen 7 7800X3D",
                     "matched_note": "AM5", "state": "ok"}]


def test_catalog_match_note_also_shows_wattage_when_thats_the_shared_spec():
    # "750W"만으로는(모델명 없이) 특정 제품을 지목한 게 아니라 다른 파워도 다 갖고 있는 흔한 숫자라
    # 카탈로그 대응을 하지 않는다 — 전체 모델명을 적어야 대응된다(아래 다른 테스트에서 확인).
    pool = {"파워": [_cand("파워", "Thermaltake Toughpower GF A3 750W", wattage_w=750),
                    _cand("파워", "Enermax Revolution D.F. X 750W", wattage_w=750)]}
    rows = preview_current_specs({"파워": "Thermaltake Toughpower GF A3 750W"}, pool, SLOT_STRUCTURE)
    assert rows[0]["state"] == "ok" and rows[0]["matched_note"] == "750W"
    assert preview_current_specs({"파워": "750W"}, pool, SLOT_STRUCTURE)[0]["state"] == "warn"


def test_unrecognisable_text_is_warn_and_echoes_the_original():
    rows = preview_current_specs({"메인보드": "옛날에 산 알 수 없는 보드"}, POOL, SLOT_STRUCTURE)
    assert rows == [{"part": "메인보드", "original": "옛날에 산 알 수 없는 보드", "matched": "옛날에 산 알 수 없는 보드",
                     "matched_note": "확인 가능한 스펙이 없습니다.", "state": "warn"}]


def test_model_name_rule_inference_is_warn_with_a_note_that_says_so():
    # 카탈로그엔 없지만(단종) 모델명 규칙으로 소켓만 추정되는 경우 — resolve_owned_parts의 inferred 경로.
    rows = preview_current_specs({"CPU": "i5-13600K"}, {"CPU": []}, SLOT_STRUCTURE)
    assert rows[0]["state"] == "warn"
    assert rows[0]["matched"] == "i5-13600K"
    assert "추정" in rows[0]["matched_note"] and "LGA1700" in rows[0]["matched_note"]


def test_blank_or_missing_slots_are_left_out_not_marked_unknown():
    rows = preview_current_specs({"CPU": "  ", "GPU": "", "RAM": "DDR5 32GB"}, POOL, SLOT_STRUCTURE)
    assert [r["part"] for r in rows] == ["RAM"]        # RAM은 카탈로그 대응을 안 하지만(용량만으론 특정 불가) 여전히 한 행은 나온다


def test_rows_follow_slot_structure_order_not_input_order():
    rows = preview_current_specs({"파워": "750W", "CPU": "Ryzen 7 7800X3D"}, POOL, SLOT_STRUCTURE)
    assert [r["part"] for r in rows] == ["CPU", "파워"]


def test_non_dict_current_specs_returns_no_rows():
    assert preview_current_specs(None, POOL, SLOT_STRUCTURE) == []
    assert preview_current_specs("아무 텍스트", POOL, SLOT_STRUCTURE) == []
