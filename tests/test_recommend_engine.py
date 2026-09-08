#!/usr/bin/env python3
"""
추천 엔진 회귀 검증 — 목업이 약속한 것을 코드가 지키는지.

pytest 없이 그대로 실행된다:

    python tests/test_recommend_engine.py

**모델을 부르지 않는다.** 기본 모드가 `rule` 이고 리뷰 소스 기본값이 `synthetic`
이라 키 없이 전부 돈다. 여기서 확인되지 않는 것은 `RECOMMEND_MODE=strands` 의
모델 왕복이다 — 키가 있어야 확인된다.

[왜 목업을 검사 기준으로 쓰는가]
`docs/목업/pc-부품.html` 은 발표에 나갈 화면이다. 화면과 API 가 다른 숫자를
말하면 둘 중 하나는 거짓말이 되는데, 어느 쪽이 틀렸는지는 발표장에서 밝혀진다.
그래서 목업이 그려 둔 판정·금액·구성을 여기서 고정한다.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import pipeline                               # noqa: E402
from app.engine.packs.pc import pack                          # noqa: E402
from app.engine.run import recommend                          # noqa: E402
from app.engine.schemas import Evidence, Indicators, Verdict  # noqa: E402
from app.engine.verify import verdict_from                    # noqa: E402

ANSWERS = {"refresh_hz": "144Hz", "reuse": "케이스만", "priority": "상관없음"}
QUERY = "〈오르카 프로토콜〉 QHD 상옵으로 돌리고 싶어요. 예산 120만 원이고 3년 된 본체 쓰고 있습니다"


def check_mockup_verdicts() -> None:
    """
    목업 3단계 표의 여섯 행이 그대로 나와야 한다.

    `verify.py` 의 두 임계값(MIN_RELEVANT · REFUTE_RATIO)이 조용히 흘러가지 않게
    하려는 검사다. 값을 만지면 여기서 몇 행이 뒤집힌다.
    """
    expected = {
        "gpu-temp": Verdict.REFUTED,        # 214건 중 47건 (.220)
        "gpu-power": Verdict.CONFIRMED,     # 반증 사례 없음
        "cpu-cooler": Verdict.REFUTED,      # 178건 중 63건 (.354)
        "psu-noise": Verdict.PARTLY,        # 96건 중 11건 (.115) — 반증선 아래
        "ssd-write": Verdict.NO_EVIDENCE,   # 닿는 표본 3건 — 임계 미만
        "ram-xmp": Verdict.CONFIRMED,       # Q&A 포함, 반증 없음
    }
    r = recommend(QUERY, answers=ANSWERS)
    got = {cv.claim.claim_id: cv.verdict for cv in r.claims}
    assert got == expected, f"목업 판정과 다릅니다: {got}"
    print("  ✓ 목업 3단계 여섯 행이 그대로 재현된다")


def check_no_evidence_beats_refute() -> None:
    """
    표본이 부족하면 어긋난 사례가 있어도 **근거 없음**이다.

    3건으로 반증을 선언하면 9/7 15시 엘리베이터 논쟁에서 팀이 고른 쪽(모르는
    것을 모른다고 말한다)이 아니라 반대쪽으로 가는 것이다.
    """
    thin = Evidence(samples={"리뷰": 200}, relevant=3, hits=3)
    assert verdict_from(thin) is Verdict.NO_EVIDENCE, "표본 부족인데 판정을 했다"
    print("  ✓ 표본 부족이 반증보다 먼저 걸린다")


def check_refuted_is_not_excluded() -> None:
    """
    **구속 조건 ①** — 반증돼도 후보에서 빼지 않는다.

    목업 공개 화면: *"판정은 후보를 제외하지 않는다. 반증된 항목도 목록에 남고
    경고만 붙는다."* 그래픽카드는 반증됐지만 대안이 없어 유지 + 경고로 간다.
    """
    r = recommend(QUERY, answers=ANSWERS)
    refuted = {cv.claim.claim_id for cv in r.claims if cv.verdict is Verdict.REFUTED}
    assert "gpu-temp" in refuted, "그래픽카드 온도 주장이 반증되지 않았다"

    gpu = [ln for ln in r.set if ln.category == "GPU"]
    assert gpu, "반증된 그래픽카드가 세트에서 사라졌다"
    assert gpu[0].warning, "반증된 품목에 경고가 붙지 않았다"
    print("  ✓ 반증된 품목이 경고를 달고 세트에 남는다")


def check_reviews_do_not_rank() -> None:
    """
    **구속 조건 ②** — 리뷰는 순위에 직접 반영하지 않는다.

    목업 공개 화면: *"리뷰는 순위에 직접 반영하지 않는다. 스펙 주장의 진위
    판정에만 쓴다."* 이 약속이 거짓이 되면 공개 화면 전체가 무너진다.

    두 겹으로 검사한다. 시그니처에 판정이 없어야 하고(받을 수 없으면 못 쓴다),
    리뷰 라벨을 뒤집어도 3단계 ①②의 결과가 같아야 한다.
    """
    params = set(inspect.signature(pipeline.rank).parameters)
    assert not (params & {"verdicts", "claims", "reviews", "source"}), (
        f"rank() 가 판정을 받을 수 있게 됐다: {params}"
    )

    known = dict(ANSWERS)
    known.update(game="오르카 프로토콜", budget=1_200_000)
    reqs = pipeline.step2_requirements(pack, known)
    base = [p["code"] for p in pipeline.rank(pack, reqs, 1_200_000, known)]

    # 라벨을 전부 뒤집는다 — 모든 주장이 반증되는 세계.
    from app.engine.packs.pc import REVIEW_LABELS
    from app.reviews.synthetic import SyntheticReviews

    flipped = SyntheticReviews({cid: {**label, "hits": label["relevant"]}
                                for cid, label in REVIEW_LABELS.items()})
    chosen = pipeline.rank(pack, reqs, 1_200_000, known)
    verdicts = pipeline.step3_verify(pack, chosen, flipped)
    assert all(cv.verdict is not Verdict.CONFIRMED for cv in verdicts), "라벨이 안 뒤집혔다"

    after = [p["code"] for p in pipeline.rank(pack, reqs, 1_200_000, known)]
    assert base == after, f"리뷰가 순위를 바꿨다: {base} → {after}"
    print("  ✓ 리뷰가 순위에 닿지 못한다 (시그니처 + 동작)")


def check_verdict_changes_the_set() -> None:
    """
    **검증이 세트를 바꾼다.** 반증이 화면 장식이 아니라 구성에 관여한다.

    목업: *"쿨러 34,000원은 단계 3에서 CPU 기본 쿨러 주장이 반증되며 편성된
    항목이다."* 이 경로가 없으면 3단계 전체가 설명용이 된다.
    """
    r = recommend(QUERY, answers=ANSWERS)
    cooler = [ln for ln in r.set if ln.category == "쿨러"]
    assert cooler, "반증됐는데 쿨러가 편성되지 않았다"
    assert cooler[0].added_by_claim == "cpu-cooler", (
        f"쿨러가 어느 판정 때문에 들어왔는지 추적되지 않는다: {cooler[0].added_by_claim}"
    )
    print("  ✓ 반증 판정이 세트에 품목을 편성한다")


def check_mockup_budget() -> None:
    """목업 4단계 배분 표와 같은 금액이 나와야 한다 — 합계 1,187,000 / 잔액 13,000."""
    r = recommend(QUERY, answers=ANSWERS)
    assert r.budget == 1_200_000, f"예산 추출이 틀렸다: {r.budget}"
    assert r.spent == 1_187_000, f"목업 배분 표와 합계가 다르다: {r.spent}"
    assert not [ln for ln in r.set if ln.category == "케이스"], (
        "케이스를 재사용한다고 했는데 세트에 들어갔다"
    )
    print("  ✓ 합계 1,187,000 · 잔액 13,000 · 케이스 재사용")


def check_reasons_link_to_verdicts() -> None:
    """근거 문장이 판정과 일대일로 연결돼야 한다 — 설명이 지어낸 것이 아니라는 증거."""
    r = recommend(QUERY, answers=ANSWERS)
    ids = {cv.claim.claim_id for cv in r.claims}
    linked = [x for x in r.reasons if x.claim_id]
    assert linked, "판정과 연결된 근거 문장이 하나도 없다"
    for reason in linked:
        assert reason.claim_id in ids, f"세트에 없는 주장을 설명한다: {reason.claim_id}"
    print(f"  ✓ 근거 {len(linked)}문장이 전부 판정과 연결된다")


def check_asks_before_recommending() -> None:
    """되묻기가 남으면 추천을 만들지 않는다 — 모르는 채로 세트를 짜지 않는다."""
    r = recommend(QUERY)
    assert r.needs_input, "물어볼 것이 있는데 그냥 추천했다"
    assert not r.set, "되묻는 중인데 세트가 나왔다"
    assert r.budget == 1_200_000, "되묻는 중에도 알아낸 것은 남아야 한다"
    print(f"  ✓ 모르는 것 {len(r.needs_input)}건을 먼저 묻는다")


def check_indicators_cannot_be_merged() -> None:
    """
    §7 세 지표에 **종합 점수 필드가 없어야** 한다.

    기획안 §7: 합치는 순간 가중치를 정당화해야 하는데 근거가 없다. 필드가 없으면
    화면도 못 합친다 — 규약이 아니라 구조로 막는 자리다.
    """
    banned = {"score", "total_score", "trust", "overall", "combined"}
    fields = set(Indicators.model_fields)
    assert not (fields & banned), f"지표를 합칠 수 있는 필드가 생겼다: {fields & banned}"

    r = recommend(QUERY, answers=ANSWERS)
    i = r.indicators
    assert i.conditions_total and i.verdicts and i.review_risk_buckets, "지표가 비었다"
    # 조작 확률은 이진 판정이 아니라 분포다.
    assert len(i.review_risk_buckets) >= 3, "조작 확률이 분포가 아니다"
    print("  ✓ 세 지표가 따로 나오고 합칠 필드가 없다")


def main() -> int:
    checks = [
        check_mockup_verdicts,
        check_no_evidence_beats_refute,
        check_refuted_is_not_excluded,
        check_reviews_do_not_rank,
        check_verdict_changes_the_set,
        check_mockup_budget,
        check_reasons_link_to_verdicts,
        check_asks_before_recommending,
        check_indicators_cannot_be_merged,
    ]
    failed = 0
    print("추천 엔진 검증")
    for fn in checks:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print("전부 통과" if not failed else f"{failed}건 실패")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
