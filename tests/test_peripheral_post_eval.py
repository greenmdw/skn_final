"""사용기 분석 정답표 평가 로직(`peripheral_post_eval`) — DB·모델 호출 없음."""
from __future__ import annotations

from src.engine import peripheral_post_eval as ev

PURPOSES = {"mouse": {"office": "사무·문서", "fps": "경쟁 게임", "game": "게임(일반)", "many_buttons": "버튼을 많이 쓰는 게임·작업"}}
SITUATIONS = {"quiet_place": "조용해야 함", "small_desk": "좁은 책상"}

MD = """
| ID | 손 크기 | 공통 상황 | 마우스 | 키보드 | 모니터 | 스피커 |
|---|---|---|---|---|---|---|
| P06 | 보통 | — | 경쟁 게임 | 경쟁 게임 | 경쟁 게임 | 영화·게임 |
| P09 | 작은 편 | 조용해야 함, 좁은 책상 | 게임(일반) | 게임(일반) | 게임(일반) | 작은 음량 |
| P03 | 큰 편 | — | 버튼을 많이 쓰는 게임 | 게임(일반) | 몰입 게임·영화 | 영화·게임 |

| 번호 | 작성자 | 작성일 | 기간 | 결론 | 좋게 쓸 것 | 아쉽게 쓸 것 | 성향 |
|---|---|---|---|---|---|---|---|
| A1-1 | P06 | 2026-08-16 | 4주 | 추천 | 가벼움 | 엄지 | 무게: 매우 가벼움 / 크기: 적당 |
| A1-2 | P09 | 2026-10-06 | 3주 | 조건부 | 길이 | 흔들림 | 무게: 너무 가벼움 / 크기: 약간 큼 |
| A1-3 | P03 | 2026-10-01 | 2주 | 비추천 | 배터리 | 높이 | 크기: 작음 / 무게: 너무 가벼움 / 클릭 소리: 또렷·큼 |
| E1-1 | P06 | 2026-10-01 | 1주 | 추천 | - | - | - |
"""


def _gold():
    return ev.parse_gold(MD, PURPOSES, SITUATIONS)


def test_parse_gold_reads_hand_purposes_situations_and_taste():
    g = _gold()
    assert set(g) == {"A1-1", "A1-2", "A1-3"}               # E 묶음(비교 글)은 종류가 없어 제외
    assert g["A1-1"].hand == "medium" and g["A1-1"].purposes == {"fps"}
    assert g["A1-1"].taste == {"weight_feel": "light"}       # "적당"은 쪽이 아니라 넣지 않는다
    assert g["A1-2"].hand == "small" and g["A1-2"].purposes == {"game"}
    assert g["A1-2"].situations == {"quiet_place", "small_desk"}
    assert g["A1-2"].taste == {"weight_feel": "light", "size_feel": "big"}
    assert g["A1-3"].purposes == {"many_buttons"}            # "버튼을 많이 쓰는 게임" ← 라벨 앞부분
    assert g["A1-3"].taste == {"size_feel": "small", "weight_feel": "light", "click_sound": "loud"}


def test_unmapped_labels_are_listed_not_dropped():
    g = ev.parse_gold(MD.replace("| 경쟁 게임 | 경쟁 게임 | 경쟁 게임 | 영화·게임 |", "| 없는목적 | - | - | - |"),
                      PURPOSES, SITUATIONS)
    assert g["A1-1"].unmapped == ["없는목적"] and g["A1-1"].purposes == set()


def _row(attribute, side=None, direction="good", hand="medium", purposes=("fps",), situations=()):
    return {"attribute": attribute, "direction": None if side else direction, "side": side, "hand_size": hand,
            "purposes": list(purposes), "situations": list(situations)}


def test_compare_post_matches_and_flags_differences():
    g = _gold()["A1-2"]
    rows = [_row("weight_feel", "light", hand="small", purposes=("game", "docs"), situations=("quiet_place", "portable")),
            _row("size_feel", "small", hand="small", purposes=("game", "docs"), situations=("quiet_place", "portable"))]
    r = ev.compare_post(g, rows, kind_purposes={"office", "fps", "game", "many_buttons"})
    assert r.hand == ("small", "small")
    assert r.taste == {"weight_feel": "match", "size_feel": "conflict"}
    assert r.purposes_other_kind == {"docs"} and r.purposes_extra == set() and r.purposes_missing == set()
    assert r.situations_missing == {"small_desk"} and r.situations_extra == {"portable"}


def test_taste_missing_mixed_and_no_evidence():
    g = _gold()["A1-3"]
    rows = [_row("size_feel", "small", hand="large"), _row("size_feel", "big", hand="large")]
    r = ev.compare_post(g, rows)
    assert r.taste == {"size_feel": "mixed", "weight_feel": "missing", "click_sound": "missing"}
    empty = ev.compare_post(g, [])
    assert empty.evidence == 0 and set(empty.taste.values()) == {"missing"} and empty.purposes_missing == {"many_buttons"}


def test_summarize_counts():
    g = _gold()
    results = [ev.compare_post(g["A1-1"], [_row("weight_feel", "light")]), ev.compare_post(g["A1-3"], [])]
    s = ev.summarize(results)
    assert s["posts"] == 2 and s["posts_without_evidence"] == 1 and s["evidence_total"] == 1
    assert s["hand_checked"] == 1 and s["hand_match"] == 1
    assert s["taste"] == {"match": 1, "missing": 3}
