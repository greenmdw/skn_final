"""서로 다른 두 견적의 기준별 비교표 — 기준마다 따로 값을 놓고, 확인 못 한 값은 우열을 지어내지 않으며, 종합 우열은 말하지 않는다."""
from __future__ import annotations

from src.services.quote_criteria import build_criteria, facts_lines


def _side(**kw):
    base = {"incompatible": 0, "compat_ok": 10, "balance_ok": 3, "balance_short": 0, "gpu_tier": 7.0, "cpu_tier": 9.0,
            "ram_gb": 16, "vram_gb": 16, "total": 2_000_000}
    return {**base, **kw}


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_each_criterion_names_which_side_is_better_in_its_own_direction():
    rows = _by_key(build_criteria(_side(compat_ok=15, gpu_tier=8.0, total=2_280_000), _side(compat_ok=12, gpu_tier=7.0, total=2_120_000)))
    assert rows["compat_ok"]["better"] == "a"            # 통과 수는 많을수록 좋다
    assert rows["gpu_tier"]["better"] == "a"             # 등급은 높을수록
    assert rows["total"]["better"] == "b"                # 총액은 낮을수록
    assert rows["cpu_tier"]["better"] == "tie"           # 같으면 같음
    assert rows["total"]["a_text"] == "2,280,000원" and rows["gpu_tier"]["a_text"] == "8"


def test_the_confirmed_parts_line_is_informational_and_never_ranked():
    a, b = _side(confirmed_parts=4, parts=8), _side(confirmed_parts=7, parts=8)
    row = _by_key(build_criteria(a, b))["confirmed_parts"]
    assert row["info"] is True and row["better"] is None and row["a_text"] == "4/8개" and row["b_text"] == "7/8개"
    text = "\n".join(facts_lines(build_criteria(a, b), "견적 1", "견적 2"))
    assert "카탈로그로 확정된 부품: 견적 1 4/8개 / 견적 2 7/8개" in text and "확인 못 함'이 됩니다" in text


def test_a_value_that_is_unknown_on_either_side_is_not_ranked():
    rows = _by_key(build_criteria(_side(cpu_tier=None), _side(cpu_tier=9.0)))
    assert rows["cpu_tier"]["better"] is None and rows["cpu_tier"]["a_text"] == "확인 못 함"


def test_balance_rows_are_left_out_when_the_purpose_was_not_given():
    rows = _by_key(build_criteria(_side(balance_ok=None, balance_short=None), _side(balance_ok=None, balance_short=None)))
    assert "balance_ok" not in rows and "balance_short" not in rows and "gpu_tier" in rows


def test_facts_lines_never_declare_an_overall_winner():
    lines = facts_lines(build_criteria(_side(compat_ok=15), _side(compat_ok=12, gpu_tier=None)), "견적 1", "견적 2")
    text = "\n".join(lines)
    assert "견적 1 쪽이 높음" in text and "한쪽이라도 확인 못 해 비교하지 않음" in text
    assert "종합적으로 더 낫다고 판단하지 않습니다" in text
    assert facts_lines([], "견적 1", "견적 2") == []


def test_game_lines_check_each_quote_against_the_table_with_its_own_values():
    from src.services.quote_criteria import game_lines

    rows = build_criteria(_side(gpu_tier=3.0, vram_gb=4, ram_gb=8), _side(gpu_tier=9.0, vram_gb=16, ram_gb=32))
    out = game_lines(rows, "R01", "R02", "R02에서 롤이랑 배그 돌아가?")
    first, second = out.split("[R02]")
    assert out.startswith("[R01]") and "롤" in first and "배그" in first
    assert "⚠ 미달" in first and "⚠ 미달" not in second and "표의 권장 사양을 모두 채움" in second


def test_game_lines_say_the_game_is_missing_only_when_it_is_really_not_in_the_table():
    from src.services.quote_criteria import game_lines

    assert "게임 요구 사양 표에 없어" in game_lines(build_criteria(_side(), _side()), "R01", "R02", "롤러코스터 타이쿤 돼?")


def test_the_total_gap_is_computed_in_the_facts_so_the_chat_can_quote_it():
    text = "\n".join(facts_lines(build_criteria(_side(total=2_280_000), _side(total=2_120_000)), "26", "27"))
    assert "27 쪽이 낮음 (차이 160,000원)" in text
    assert "차이" not in "\n".join(l for l in facts_lines(build_criteria(_side(total=2_000_000), _side(total=2_000_000)), "26", "27") if "견적 총액" in l)
