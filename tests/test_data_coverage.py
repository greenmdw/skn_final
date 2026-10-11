"""데이터 범위 점검 — "기본값으로 눌렀더니 비어 나오는" 종류의 문제를 미리 찾는다 (2026-10-07).

주변기기 모니터가 기본 해상도(FHD 144Hz)에서 항상 비어 나온 것은 코드 오류가 아니라 카탈로그에 그 조건의 제품이 없어서였다. 이런 빈틈은
코드를 읽어서는 안 보이고 조건 조합을 훑어야 보인다. 여기서는
  1) 카탈로그의 스펙·가격이 얼마나 채워졌는지(회귀 기준선),
  2) 주변기기 해상도·용도 조합마다 결과가 나오는지,
  3) PC 추천이 용도 × 예산 × 우선순위 조합에서 죽지 않고 일관된 결과를 내는지
를 본다. LLM 은 부르지 않는다(모의 모드). 일회용 DB 의 시드 카탈로그를 쓴다.
기대가 바뀌는 것은 "나쁜 일"이 아니라 데이터가 바뀌었다는 신호다 — 이 파일의 기준표를 함께 고친다.
"""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from tests.test_list_history_http import _signed_up
    from src.engine.stage3_0_candidates import load_pc_catalog


# ── 1. 카탈로그 스펙·가격 채움 정도 ───────────────────────────────────────────────────────────

# 슬롯 → 반드시 100% 채워져야 하는 스펙(없으면 호환·성능 검사가 "모름"으로 빠진다)
REQUIRED_SPECS = {
    "CPU": ["socket", "mem_type", "perf_tier"], "메인보드": ["socket", "mem_type", "form_factor"], "RAM": ["mem_type", "capacity_gb"],
    "파워": ["wattage_w"], "케이스": ["supports_form_factors"], "쿨러": ["cooling_type"], "저장장치": ["capacity_gb"],
}


@pytest.fixture(scope="module")
def pool():
    os.environ.pop("CATALOG_SOURCE", None)
    return load_pc_catalog(lambda _m: None)


def test_every_catalog_product_has_a_positive_price(pool):
    bad = [f"{slot}: {c.name}" for slot, cands in pool.items() for c in cands if not c.price or c.price <= 0]
    assert bad == [], bad[:10]


@pytest.mark.parametrize("slot", sorted(REQUIRED_SPECS))
def test_required_specs_are_filled_for_every_product(pool, slot):
    missing = [f"{c.name} 에 {key} 없음" for c in pool[slot] for key in REQUIRED_SPECS[slot] if c.specs.get(key) in (None, "", [])]
    assert missing == [], f"{slot}: {len(missing)}건\n" + "\n".join(missing[:10])


def test_gpu_performance_tier_is_filled_for_consumer_cards(pool):
    """일반 소비자용 그래픽카드(GeForce·Radeon RX)는 성능 등급이 있어야 추천 점수·균형 판정에 쓰인다. 워크스테이션 카드는 예외."""
    workstation = ("quadro", "rtx a", "ada generation", "radeon pro", "rtx pro", "w7", "w6", "w5")
    missing = [c.name for c in pool["GPU"] if c.specs.get("perf_tier") is None and not any(w in c.name.lower() for w in workstation)]
    assert missing == [], f"성능 등급이 없는 일반 그래픽카드 {len(missing)}개: {missing[:8]}"


def test_known_gap_gpu_interface_is_not_in_the_catalog_yet(pool):
    """알려진 빈틈 — GPU 의 PCIe 인터페이스는 카탈로그에 없다(0건). 실시간 검색이 interface 를 가져와도 호환 검사에는 쓸 곳이 없다.
    데이터가 채워지면 이 테스트가 깨지고, 그때 기준표와 호환 검사 연결을 함께 점검한다."""
    assert sum(1 for c in pool["GPU"] if c.specs.get("interface")) == 0


# ── 2. 주변기기: 해상도 × 용도 조합마다 결과가 나오는가 ───────────────────────────────────────

PERIPHERAL_KINDS = ["monitor", "keyboard", "mouse", "speaker"]
KNOWN_EMPTY_MONITOR_RESOLUTIONS = {"FHD_144"}        # 카탈로그에 FHD(1080p)이면서 144Hz 이상인 모니터가 없다(기본값을 QHD 로 바꾼 이유)


def _recommend(client, **body):
    lid = client.post("/session").json()["list_id"]
    r = client.post(f"/session/{lid}/peripherals/recommend", json={"kinds": PERIPHERAL_KINDS, **body})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def peripheral_grid():
    client = _signed_up()
    grid = {}
    for resolution in (None, "FHD_144", "QHD_165", "4K"):
        for purpose in (None, "game", "office"):
            body = {k: v for k, v in (("resolution", resolution), ("purpose", purpose)) if v}
            grid[(resolution, purpose)] = _recommend(client, **body)
    return grid


def test_the_default_request_returns_every_kind_including_a_monitor(peripheral_grid):
    data = peripheral_grid[(None, None)]
    assert {i["kind"] for i in data["items"]} == set(PERIPHERAL_KINDS), data.get("empty")


def test_non_monitor_kinds_are_never_empty_for_any_combination(peripheral_grid):
    for key, data in peripheral_grid.items():
        kinds = {i["kind"] for i in data["items"]}
        assert {"keyboard", "mouse", "speaker"} <= kinds, (key, data.get("empty"))


def test_monitor_is_empty_only_for_the_known_unavailable_resolutions(peripheral_grid):
    empty = {res for (res, _purpose), data in peripheral_grid.items()
             if res and "monitor" not in {i["kind"] for i in data["items"]}}
    assert empty == KNOWN_EMPTY_MONITOR_RESOLUTIONS, f"모니터가 비는 해상도가 바뀌었다: {sorted(empty)} — 카탈로그가 바뀌었는지 확인하고 기준표를 고친다"


def test_an_empty_monitor_explains_why_instead_of_returning_nothing(peripheral_grid):
    data = peripheral_grid[("FHD_144", None)]
    reasons = {e["kind"]: e["reason"] for e in data.get("empty", [])}
    assert "monitor" in reasons and "카탈로그에 없습니다" in reasons["monitor"]


# ── 3. PC 추천: 용도 × 예산 × 우선순위 ───────────────────────────────────────────────────────

PURPOSES = {"game": "게임용", "office": "사무용", "creation": "영상 편집용"}
BUDGETS = [600_000, 900_000, 1_200_000, 1_800_000, 3_000_000, 5_000_000]
PRIORITIES = {"value": "가성비 위주", "performance": "성능 위주"}
FEASIBLE_FROM = 1_800_000                           # 이 예산부터는 모든 조합이 추천을 내야 한다


def _run(client, purpose_word, budget, priority_word):
    lid = client.post("/session").json()["list_id"]
    client.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    state = client.post(f"/session/{lid}/message",
                        json={"text": f"{purpose_word} PC 예산 {budget // 10_000}만원 {priority_word}"}).json()
    if not state.get("can_recommend"):
        return {"status": "not_ready", "state": state}
    accepted = client.post(f"/session/{lid}/recommend")
    assert accepted.status_code == 202, accepted.text
    return client.get(f"/session/{lid}/result").json()


@pytest.fixture(scope="module")
def recommendation_grid():
    client = _signed_up()
    return {(p, b, pr): _run(client, word, b, pword)
            for p, word in PURPOSES.items() for b in BUDGETS for pr, pword in PRIORITIES.items()}


def test_every_combination_ends_in_a_clear_status(recommendation_grid):
    """멈추거나 500 이 나는 조합이 없다 — done 이거나, 이유가 있는 failed 다."""
    bad = {k: v.get("status") for k, v in recommendation_grid.items() if v.get("status") not in ("done", "failed")}
    assert bad == {}, bad


def test_feasible_budgets_always_produce_a_recommendation(recommendation_grid):
    failed = {k: (v.get("status"), (v.get("error") or {}).get("code")) for k, v in recommendation_grid.items()
              if k[1] >= FEASIBLE_FROM and v.get("status") != "done"}
    assert failed == {}, f"충분한 예산인데 추천이 안 나온 조합: {failed}"


def test_a_finished_recommendation_is_complete_and_priced(recommendation_grid):
    for key, data in recommendation_grid.items():
        if data.get("status") != "done":
            continue
        selected = [i for i in data["items"] if i["selected"]]
        assert len(selected) == 8, (key, [i["slot"] for i in selected])
        assert all(i["price"] and i["price"] > 0 for i in selected), key
        assert data["totals"]["selected_price"] == sum(i["price"] * i["qty"] for i in selected), key


def test_the_budget_flag_matches_the_arithmetic(recommendation_grid):
    for key, data in recommendation_grid.items():
        if data.get("status") != "done":
            continue
        totals = data["totals"]
        assert totals["over_budget"] == (totals["selected_price"] > key[1]), (key, totals)


def test_a_large_unused_budget_is_explained_to_the_user(recommendation_grid):
    """예산의 절반 넘게 남는데 아무 안내가 없으면 사용자는 왜 이 구성인지 알 수 없다 — 안내(budget_notice)가 있어야 한다."""
    silent = {k: round(v["totals"]["selected_price"] / k[1], 2) for k, v in recommendation_grid.items()
              if v.get("status") == "done" and v["totals"]["selected_price"] < k[1] * 0.5 and not v.get("budget_notice")}
    assert silent == {}, f"예산이 절반 넘게 남는데 안내가 없는 조합(총액/예산): {silent}"


@pytest.mark.xfail(reason="관찰된 이상(2026-10-07): 게임·성능 우선에서 예산 300만→500만원인데 총액이 2,187,280→2,032,610원으로 줄었다. "
                          "요구 성능을 채운 뒤 남는 예산을 쓰지 않는 설계(budget_notice)인지, 예산 배분의 결함인지 확인이 필요하다.",
                   strict=False)
def test_a_bigger_budget_never_gets_a_cheaper_performance_build(recommendation_grid):
    """성능 우선인데 예산을 더 줬더니 더 싼(=더 약한) 구성이 나오면 예산 배분이 이상한 것이다(허용 오차 5%)."""
    for purpose in PURPOSES:
        totals = [(b, recommendation_grid[(purpose, b, "performance")]["totals"]["selected_price"])
                  for b in BUDGETS if recommendation_grid[(purpose, b, "performance")].get("status") == "done"]
        for (b1, t1), (b2, t2) in zip(totals, totals[1:]):
            assert t2 >= t1 * 0.95, f"{purpose}: 예산 {b1:,}→{b2:,} 인데 총액 {t1:,}→{t2:,}"
