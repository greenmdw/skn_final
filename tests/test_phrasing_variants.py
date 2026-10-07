"""말투·표기 변형 테스트 — 사용자가 같은 뜻을 여러 방식으로 말해도 같게 읽히는가 (2026-10-07).

실제 사용에서 나온 버그("진행해줘"가 동의로 안 읽힘, "엔비디아 5070"이 카탈로그에 없다고 판정, "라이젠 9000"이 무시됨)는 모두
**같은 뜻의 다른 표현**에서 났다. 한 표현씩 고치는 대신 변형을 표로 모아 두고 한꺼번에 확인한다. LLM 은 부르지 않는다
(규칙 코드와 카탈로그만). 결과가 기대와 다르면 그 표현이 새 버그다 — 표에 추가하고 코드를 고친다.
"""
from __future__ import annotations

import os

import pytest

from src.agent import conditions_agent as ca
from src.engine.slot_rules import _parse_won, extract_computer

MARKER_REPLY = f"'RTX 6090'는 저희 DB에 없는 상품으로 확인됩니다. {ca.SEARCH_PERMISSION_MARKER}"

# ── 1. 검색 동의 ────────────────────────────────────────────────────────────────────────────

AFFIRM = [
    "응", "응응", "ㅇㅇ", "ㅇㅋ", "오케이", "ok", "OK", "okay", "네", "넵", "넹", "예", "옙", "그래", "그래요", "좋아", "좋아요",
    "좋습니다", "콜", "ㄱㄱ", "고고", "부탁해", "부탁해요", "부탁드려요", "부탁드립니다", "그렇게 해", "그렇게 해줘", "해줘", "해 줘",
    "해주세요", "해봐", "해봐요", "찾아줘", "찾아봐", "찾아봐줘", "찾아 주세요", "검색해줘", "검색해 줘", "검색해주세요", "검색해봐",
    "검색해 봐", "진행해", "진행해줘", "진행해 주세요", "진행해주세요", "진행하세요", "진행할게요", "진행해도 돼", "진행해도 돼요",
    "외부 검색 진행해줘", "외부 검색해줘", "네 진행해주세요", "응 진행해줘", "어 해줘", "그럼 찾아봐", "그럼 해줘", "음 해줘",
    "어 부탁해", "네네", "ㅇㅋㅇㅋ", "좋아 진행해", "그래 검색해줘", "네, 검색해 주세요.", "응!", "네~", "해줘요", "그렇게 진행해줘",
]

DENY_OR_OTHER = [
    "아니", "아니요", "아니오", "아뇨", "ㄴㄴ", "싫어", "싫어요", "안 해도 돼", "안해도돼요", "괜찮아", "괜찮아요", "됐어", "됐어요",
    "패스", "그만", "취소", "다음에", "나중에", "필요없어", "필요 없어요", "하지마", "하지 마세요", "진행하지마", "검색하지마",
    "검색은 안 해도 돼요", "찾지마", "RTX 5090으로 해줘", "다른 제품으로 찾아줘", "호환은 문제없어?", "가격이 얼마야",
    "이거 말고 다른 거 추천해줘", "", "ㅇ", "ㅜㅜ", "예산을 200만원으로 바꿔줘", "그래픽카드 말고 CPU 알려줘",
]


@pytest.mark.parametrize("answer", AFFIRM)
def test_natural_korean_yes_is_read_as_consent(answer):
    assert ca.is_search_confirmation(MARKER_REPLY, answer) is True, answer


@pytest.mark.parametrize("answer", DENY_OR_OTHER)
def test_denials_and_new_requests_are_not_consent(answer):
    assert ca.is_search_confirmation(MARKER_REPLY, answer) is False, answer


# ── 2. 금액 표기 ────────────────────────────────────────────────────────────────────────────

WON = [
    ("150만원", 1_500_000), ("150만 원", 1_500_000), ("150만", 1_500_000), ("예산 150만원 정도", 1_500_000),
    ("1,500,000원", 1_500_000), ("1500000원", 1_500_000), ("₩1,500,000", 1_500_000), ("삼백만원", 3_000_000),
    ("백오십만원", 1_500_000), ("2천만원", 20_000_000), ("1.5억", 150_000_000), ("100만 원 안쪽", 1_000_000),
    ("2.5만원", 25_000), ("1.5 million won", 1_500_000),
    # 앞서 말한 금액을 정정하면 정정한 쪽이 예산이다(2026-10-07 수정)
    ("2천만원 아니고 200만원", 2_000_000), ("300만원 말고 250만원", 2_500_000), ("노트북 말고 데스크탑 120만원", 1_200_000),
    ("150만원 아니라 180만원이요", 1_800_000),
]


@pytest.mark.parametrize("text,expected", WON)
def test_amount_phrasing_is_read_to_the_same_won(text, expected):
    assert _parse_won(text) == expected, text


@pytest.mark.parametrize("text", ["그냥 게임용", "예산 말고 성능이 중요해", "조용한 걸로", "한 300 정도?"])
def test_no_amount_means_no_budget_instead_of_a_guess(text):
    assert _parse_won(text) is None, text


# ── 3. 규칙 기반 조건 파서(LLM 이 꺼졌거나 실패했을 때의 경로) ──────────────────────────────────

CONDITIONS = [
    ("게임용 PC 맞춰줘 예산 150만원", {"purpose": "game", "budget_max": 1_500_000}),
    ("150만원으로 롤 돌릴 컴퓨터", {"purpose": "game", "budget_max": 1_500_000}),
    ("사무용 100만 원 정도", {"purpose": "office", "budget_max": 1_000_000}),
    ("영상 편집용인데 예산은 250만원이고 성능이 제일 중요해", {"purpose": "creation", "budget_max": 2_500_000, "priority": "performance"}),
    ("백오십만원 가성비 게임", {"purpose": "game", "budget_max": 1_500_000, "priority": "value"}),
    ("게임 하려고, 조용한 걸로 150만원", {"purpose": "game", "budget_max": 1_500_000, "priority": "quiet"}),
    ("롤이랑 발로란트 할 거예요 예산 200만원 가성비", {"purpose": "game", "budget_max": 2_000_000, "priority": "value"}),
    ("그냥 인터넷 하고 유튜브 볼 거야 80만원", {"purpose": "office", "budget_max": 800_000}),
    ("QHD로 게임할 건데 200만원", {"purpose": "game", "budget_max": 2_000_000, "resolution": "QHD_165"}),
    ("4K 게임 300만원 성능 위주", {"purpose": "game", "budget_max": 3_000_000, "resolution": "4K", "priority": "performance"}),
    ("2천만원 아니고 200만원 게임용", {"purpose": "game", "budget_max": 2_000_000}),
    ("영상편집 위주로 조용한 pc로", {"purpose": "creation", "priority": "quiet"}),          # "조용한"의 '조'가 1조원이 되지 않는다
    ("공부용으로 70만원", {"purpose": "study", "budget_max": 700_000}),
]


@pytest.mark.parametrize("text,expected", CONDITIONS)
def test_free_text_conditions_are_read_the_same_way_in_every_phrasing(text, expected):
    got = extract_computer(text)
    assert {k: got.get(k) for k in expected} == expected, (text, got)
    if "budget_max" not in expected:
        assert "budget_max" not in got, (text, got)


# ── 4. 카탈로그 제품의 표기 변형 (일회용 DB 의 실제 카탈로그) ────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

BRAND_WORDS = {"nvidia", "geforce", "amd", "radeon", "intel", "core"}


def _catalog():
    from src.db import get_conn
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    with get_conn() as conn:
        return load_candidates_by_slot_from_db(conn)


def _variants(name: str) -> dict[str, str]:
    """같은 제품을 사용자가 적을 법한 표기들."""
    words = name.split()
    out = {"원본": name, "소문자": name.lower()}
    stripped = " ".join(w for w in words if w.lower() not in BRAND_WORDS)
    if stripped and stripped != name:
        out["브랜드 낱말 없이"] = stripped
    korean = {"nvidia": "엔비디아", "geforce": "지포스", "radeon": "라데온", "amd": "AMD", "intel": "인텔"}
    mixed = " ".join(korean.get(w.lower(), w) for w in words)
    if mixed != name:
        out["한글 브랜드"] = mixed
    return out


@db
def test_every_catalog_product_is_found_again_by_its_own_name():
    """제품 이름을 그대로 쓰면 그 제품이(또는 용량만 다른 같은 제품이) 대응되어야 한다 — 이름 매칭의 가장 기본 약속."""
    from src.engine.owned_parts import _match_catalog

    misses = []
    for slot, pool in _catalog().items():
        for cand in pool:
            hits = _match_catalog(cand.name, pool)
            if cand.name not in {h.name for h in hits}:
                misses.append(f"{slot}: {cand.name} -> {[h.name for h in hits][:2]}")
    assert misses == [], f"자기 이름으로도 못 찾는 제품 {len(misses)}개:\n" + "\n".join(misses[:15])


@db
@pytest.mark.parametrize("slot", ["GPU", "CPU"])
def test_gpu_and_cpu_names_are_found_through_common_spelling_variants(slot):
    """브랜드 낱말을 빼거나 한글로 쓰거나 붙여 써도 그 제품을 후보에 포함해야 한다(후보가 여럿이면 되묻기 대상 — 없다고 하면 안 된다)."""
    from src.engine.owned_parts import _match_catalog, catalog_family_matches

    pool = _catalog().get(slot, [])
    assert pool, f"{slot} 카탈로그가 비어 있다"
    misses = []
    for cand in pool:
        for label, text in _variants(cand.name).items():
            names = {h.name for h in _match_catalog(text, pool)} | {h.name for h in catalog_family_matches(text, pool)}
            if cand.name not in names:
                misses.append(f"[{label}] {text!r} -> {sorted(names)[:2]}")
    assert misses == [], f"{slot} 표기 변형 {len(misses)}건을 못 찾음:\n" + "\n".join(misses[:20])
