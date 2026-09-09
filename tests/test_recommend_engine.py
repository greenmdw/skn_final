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
from app.engine.schemas import (  # noqa: E402
    Claim, Evidence, Indicators, Review, ReviewJudgment, Verdict,
)
from app.engine.verify import verdict_from                    # noqa: E402

ANSWERS = {"refresh_hz": "144Hz", "reuse": "케이스만", "priority": "상관없음"}
QUERY = "〈인디아나 존스: 그레이트 서클〉 QHD 상옵으로 돌리고 싶어요. 예산 120만 원이고 3년 된 본체 쓰고 있습니다"


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
    known.update(game="인디아나 존스: 그레이트 서클", budget=1_200_000)
    reqs = pipeline.step2_requirements(pack, known)
    base = [p["code"] for p in pipeline.rank(pack, reqs, 1_200_000, known)]

    # 모든 리뷰가 모든 주장을 반증하는 세계를 만든다.
    class AllContradict:
        name = "all-contradict"

        def match(self, claim, reviews):
            return [ReviewJudgment(review_id=r.review_id, bears_on=True,
                                   contradicts=True) for r in reviews]

    chosen = pipeline.rank(pack, reqs, 1_200_000, known)
    verdicts = pipeline.step3_verify(pack, chosen, matcher=AllContradict())
    assert all(cv.verdict is not Verdict.CONFIRMED for cv in verdicts), "대조기가 안 먹혔다"

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


def check_semantic_matching_is_a_step() -> None:
    """
    대조가 **코드에 있는 일**이어야 한다 — 데이터에 미리 들어 있으면 안 된다.

    소스는 문장만 주고, 닿는지·어긋나는지는 대조기가 정한다. 대조기를 갈아
    끼우면 판정이 바뀌는 것이 그 증거다(`check_reviews_do_not_rank` 가 쓰는
    AllContradict 가 같은 자리를 반대편에서 짚는다).
    """
    reviews = pack.review_source().fetch("SSD-1T")
    assert reviews, "리뷰 묶음이 비어 있다"
    assert all(r.text for r in reviews), "본문 없는 리뷰가 있다 — 대조할 것이 없다"

    # 142건 중 실측을 언급한 것은 3건뿐이다. 대조가 표본을 골라내는 일이라는 것.
    bearing = [r for r in reviews if "ssd-write" in r.bears_on]
    assert len(bearing) == 3, f"닿는 리뷰가 3건이어야 한다: {len(bearing)}"
    assert len(reviews) > 100, "골라낼 것이 없으면 대조가 시험되지 않는다"
    print(f"  ✓ 리뷰 {len(reviews)}건에서 닿는 3건을 골라낸다")


def check_reviews_belong_to_the_part() -> None:
    """
    한 품목의 주장 둘이 **같은 리뷰 묶음**을 쓴다.

    목업에서 그래픽카드의 두 주장이 똑같이 "리뷰 214"를 대조 표본으로 적은 것이
    이 사실이다. 주장마다 따로 읽으면 모델 호출이 두 배가 된다.
    """
    r = recommend(QUERY, answers=ANSWERS)
    gpu = [cv for cv in r.claims if cv.claim.claim_id.startswith("gpu-")]
    assert len(gpu) == 2, "그래픽카드 주장이 둘이어야 한다"
    assert gpu[0].evidence.samples == gpu[1].evidence.samples, (
        f"같은 품목인데 표본이 다르다: {gpu[0].evidence.samples} vs {gpu[1].evidence.samples}"
    )
    print("  ✓ 같은 품목의 두 주장이 같은 리뷰 묶음을 쓴다")


def check_high_risk_reviews_are_excluded() -> None:
    """
    조작 확률이 임계 이상인 리뷰는 **대조 표본에서 빠진다.**

    목업 공개 화면의 약속이다 — *"조작 확률 20% 이상인 리뷰는 대조 표본에서
    제외. 삭제하지 않고 별도 보관한다."* 지우지 않으므로 몇 건을 뺐는지 셀 수
    있어야 하고, 그 수가 화면에 나간다.
    """
    r = recommend(QUERY, answers=ANSWERS)
    assert all(cv.evidence.excluded_high_risk > 0 for cv in r.claims), (
        "제외된 건수가 0이다 — 필터가 안 걸렸거나 셀 수 없다"
    )

    source = pack.review_source()
    reviews = source.fetch("PSU-650")
    kept = [x for x in reviews if x.risk < source.threshold]
    psu = next(cv for cv in r.claims if cv.claim.claim_id == "psu-noise")
    assert psu.evidence.total == len(kept), (
        f"표본이 필터를 통과한 수와 다르다: {psu.evidence.total} vs {len(kept)}"
    )
    assert psu.evidence.excluded_high_risk == len(reviews) - len(kept), "제외 건수가 안 맞는다"
    print(f"  ✓ 조작 확률 {source.threshold:.0%} 이상을 대조에서 빼고 그 수를 남긴다")


def check_quotes_are_real() -> None:
    """인용이 실제 리뷰 원문에서 와야 한다 — 지어낸 인용은 근거가 아니다."""
    source = pack.review_source()
    r = recommend(QUERY, answers=ANSWERS)
    for cv in r.claims:
        if not cv.evidence.quotes:
            continue
        code = next((p["code"] for p in pack.catalog()
                     if any(c.claim_id == cv.claim.claim_id
                            for c in pack.claims_for(p["code"]))), None)
        texts = [x.text for x in source.fetch(code)]
        for q in cv.evidence.quotes:
            assert any(q in t for t in texts), f"원문에 없는 인용: {q[:30]}"
    print("  ✓ 근거 인용이 전부 실제 리뷰 원문에 있다")


def check_matcher_guardrails() -> None:
    """
    모델이 낸 판정에서 조용히 틀리는 셋을 막는다.

    셋 다 에러를 내지 않고 숫자만 바꾸는 종류다 — 검사가 없으면 새는지도 모른다.
    """
    from app.engine.match import accept

    review = Review(review_id="R1", part_code="X", text="온도가 82도까지 올라갑니다.")
    by_id = {"R1": review}

    kept = accept([
        ReviewJudgment(review_id="R1", bears_on=True, contradicts=True,
                       quote="온도가 82도까지"),
        ReviewJudgment(review_id="없는-id", bears_on=True, contradicts=True),
        ReviewJudgment(review_id="R1", bears_on=True, contradicts=True,
                       quote="이 리뷰에 없는 문장입니다"),
    ], by_id)

    assert "없는-id" not in kept, "보내지 않은 review_id 가 통과했다"
    assert kept["R1"].quote == "", "원문에 없는 인용이 남았다"

    kept2 = accept([ReviewJudgment(review_id="R1", bears_on=False, contradicts=True)], by_id)
    assert kept2["R1"].contradicts is False, "닿지 않는데 어긋난다고 셌다"

    # 수치 주장에는 수치가 있는 인용을 요구한다. 채점에서 잡힌 것이고, 이게
    # 없으면 얇은 표본이 부풀어 "근거 없음"이 "부분 확인"으로 뒤집힌다.
    spec = Claim(claim_id="c", subject="SSD", text="연속 쓰기 5,000MB/s")
    vague = Review(review_id="R2", part_code="X",
                   text="쓰기 속도는 공식 스펙만 보고 샀습니다.")
    kept3 = accept([ReviewJudgment(review_id="R2", bears_on=True, contradicts=False,
                                   quote="쓰기 속도는 공식 스펙만 보고 샀습니다.")],
                   {"R2": vague}, spec)
    assert kept3["R2"].bears_on is False, "수치 없는 인용이 수치 주장에 닿는다고 통과했다"

    measured = Review(review_id="R3", part_code="X",
                      text="실측해 보니 3,200MB/s 나옵니다.")
    kept4 = accept([ReviewJudgment(review_id="R3", bears_on=True, contradicts=True,
                                   quote="실측해 보니 3,200MB/s 나옵니다.")],
                   {"R3": measured}, spec)
    assert kept4["R3"].bears_on is True, "수치가 있는 인용까지 막았다"
    print("  ✓ 지어낸 id · 지어낸 인용 · 모순된 판정 · 수치 없는 근거를 버린다")


def check_screening_reports_zero() -> None:
    """
    제약이 **아무것도 안 걸러도** 깔때기에 행이 남아야 한다.

    외부 사실(게임 권장 사양)을 주입해도 예산이 넉넉하면 결과가 같을 수 있다 —
    요구는 바닥이지 목표가 아니기 때문이다. 그때 화면에 *"권장 사양을 주입했다"*
    만 뜨고 무엇이 달라졌는지 안 보이면, 심사위원의 *"8GB였으면 뭐가 달라집니까"*
    에 답할 것이 없다. **0을 0이라고 말하는 것**이 답이다.
    """
    twelve = recommend("〈인디아나 존스: 그레이트 서클〉 QHD 예산 120만 원", answers=ANSWERS)
    eight = recommend("〈몬스터 헌터 와일즈〉 QHD 예산 120만 원", answers=ANSWERS)

    assert twelve.screening and eight.screening, "깔때기 데이터가 없다"
    a = next(x for x in twelve.screening if x.key == "vram")
    b = next(x for x in eight.screening if x.key == "vram")
    assert a.excluded > 0, "12GB 제약이 아무것도 안 걸렀다"
    assert b.excluded == 0, "8GB 제약이 무언가를 걸렀다 — 데이터가 바뀐 것 같다"
    assert a.origin and b.origin, "제약이 어디서 왔는지가 없다"
    print(f"  ✓ 깔때기가 제약별 효과를 낸다 (12GB −{a.excluded} · 8GB −{b.excluded})")


def check_silent_failures_are_spoken() -> None:
    """
    조용히 지나가던 것 둘을 말하게 한다.

    8개 시나리오를 돌려 보고서야 보였다. 둘 다 결과는 그럴듯하게 나오고 어디에도
    사실이 안 적혔다.

    1. 모르는 게임 → 하드 제약이 하나도 없는 채로 자신 있는 세트를 냈다
    2. 예산 50만 원 → 113만 원짜리를 내면서 초과를 말하지 않았다
    """
    unknown = recommend("〈없는게임〉 QHD 예산 120만 원", answers=ANSWERS)
    assert not [r for r in unknown.requirements if r.hard], "모르는 게임인데 제약이 생겼다"
    assert unknown.notices, "하드 제약이 없는데 아무 말도 안 한다"
    assert any("보증하지 않" in n for n in unknown.notices), unknown.notices

    poor = recommend("〈인디아나 존스: 그레이트 서클〉 QHD 예산 50만 원", answers=ANSWERS)
    assert poor.spent > poor.budget, "이 시나리오는 예산을 넘겨야 한다"
    assert poor.budget_met is False, "예산을 넘겼는데 충족으로 표시된다"
    assert any("초과" in n for n in poor.notices), poor.notices
    print("  ✓ 외부 사실 없음 · 예산 초과를 응답이 말한다")


def check_engine_knows_no_domain() -> None:
    """
    엔진 코드 어디에도 도메인이 박혀 있으면 안 된다. `run.py` 의 레지스트리만 예외다.

    예전에는 두 곳이 새고 있었다. `pipeline` 이 `packs.pc` 를 임포트해
    `pack.name == "pc"` 로 분기했고(게임 이름 표를 읽으려고), 하드 제약을 품목에
    대보는 `_meets()` 가 `vram` 과 `"GPU"` 로 하드코딩돼 있었다. 여행 팩을 넣으면
    엔진을 고쳐야 했으니 `DomainPack` 이 있으나 마나였다.

    **주석과 docstring 은 보지 않는다** — PC 를 예로 들어 설명하는 것은 누출이
    아니라 문서다. `ast` 로 벗겨내고 코드만 본다.
    """
    import ast

    engine = ROOT / "app" / "engine"
    banned = ("packs", "'pc'", '"pc"', "vram", "GAMES")
    offenders = []

    for path in sorted(engine.glob("*.py")):
        if path.name == "run.py":       # 도메인을 고르는 레지스트리. 여기만 이름을 안다
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    node.body = body[1:] or [ast.Pass()]
        code = ast.unparse(tree)
        offenders += [f"{path.name}: {n}" for n in banned if n in code]

    assert not offenders, f"엔진이 도메인을 안다: {offenders}"
    print(f"  ✓ 엔진 {len(list(engine.glob('*.py'))) - 1}개 모듈이 도메인을 모른다")


def check_unscored_risk_is_never_clean() -> None:
    """
    조작 확률을 **못 잰 리뷰**를 "깨끗함"으로 처리하면 안 된다.

    예전에는 `Review.risk` 기본값이 0.0 이었다. 실 리뷰에는 확률이 안 붙어
    있으므로 전부 0.0 이 되고, 20% 필터가 **한 건도 안 거르는데 에러는 안 난다.**
    공개 화면의 약속("20% 이상은 대조 표본에서 제외")이 조용히 무력해지는 자리다.

    이제 `None` 은 "안 쟀다"이고, 대조에는 쓰되 따로 세어 근거 문장에 적는다.
    """
    from app.engine.match import LabelMatcher, gather
    from app.reviews.risk import NoRiskScorer

    claim = Claim(claim_id="c", subject="파워", text="조용합니다")
    reviews = [
        Review(review_id="a", part_code="P", text="조용해요.", bears_on=["c"]),          # 미채점
        Review(review_id="b", part_code="P", text="조용해요.", risk=0.05, bears_on=["c"]),
        Review(review_id="c2", part_code="P", text="최고예요!", risk=0.90, bears_on=["c"]),
    ]
    assert reviews[0].risk is None, "미채점 기본값이 None 이 아니다 — 0.0 이면 깨끗함으로 샌다"

    ev = gather(claim, reviews, LabelMatcher(), 0.20, NoRiskScorer())
    assert ev.excluded_high_risk == 1, f"임계 이상을 안 걸렀다: {ev.excluded_high_risk}"
    assert ev.unscored_risk == 1, f"미채점을 안 셌다: {ev.unscored_risk}"
    assert "재지 못한" in ev.note, f"근거 문장이 그 사실을 말하지 않는다: {ev.note}"
    print("  ✓ 조작 확률을 못 잰 표본을 세고 근거 문장에 적는다")


def check_domains_are_listed_even_when_missing() -> None:
    """
    팩이 없는 도메인도 **목록에는 남아야 한다.**

    2026-09-08 16시에 카테고리가 셋으로 확정됐는데(컴퓨터 조립·레시피·육아용품)
    팩은 PC 하나뿐이다. 목록에서 빼면 화면이 카테고리 선택지를 못 그리고 무엇이
    남았는지도 안 보인다 — **고를 수 없게 하되 없는 것처럼 굴지는 않는다.**

    그리고 없을 때의 에러가 **무엇을 써야 하는지 말해야 한다.** "모르는 도메인"만
    나오면 다음 사람이 소스를 뒤져야 한다.
    """
    from app.engine.run import DOMAINS, available_domains, recommend

    listed = {d["domain"]: d for d in available_domains()}
    assert set(listed) == set(DOMAINS), f"목록이 확정된 카테고리와 다르다: {list(listed)}"
    assert listed["pc"]["ready"] is True, "PC 팩이 준비 안 됨으로 나온다"
    assert any(not d["ready"] for d in listed.values()), (
        "전부 ready 다 — 팩이 다 생겼다면 이 검사를 지울 것"
    )

    try:
        recommend("아무거나", domain="recipe")
    except ValueError as e:
        assert "packs/recipe.py" in str(e), f"무엇을 써야 하는지 안 말한다: {e}"
        assert "품목 사전" in str(e), f"채울 칸을 안 말한다: {e}"
    else:
        raise AssertionError("팩이 없는데 추천이 나왔다")

    print(f"  ✓ 카테고리 {len(listed)}종이 목록에 있고, 없는 팩은 무엇을 쓸지 말한다")


def check_excerpts_can_be_withheld() -> None:
    """
    **검증과 노출은 다른 일이다.**

    9/8 17시에 *"리뷰 원문을 그대로 가져와 저장하는 것은 법적 문제가 있어 절대
    안 되며, 반드시 가공한 뒤 노출해야 한다"* 가 정해졌다. 그런데 판정의 근거로
    원문 인용을 쓰고 있었다 — 그 숫자를 지어내지 않았다는 것을 보이는 수단이었다.

    인용을 없애면 그 수단이 사라진다. 그래서 **검증은 서버 안에서 계속하고
    내보내는 것만 가린다.** 가려도 판정과 표본 수는 그대로여야 하고, 화면이
    "근거가 없다"와 "못 보여준다"를 구분할 수 있어야 한다.
    """
    from app.engine.match import LabelMatcher, gather
    from app.reviews.risk import NoRiskScorer

    claim = Claim(claim_id="c", subject="파워", text="조용합니다")
    reviews = [Review(review_id=f"r{i}", part_code="P", text="코일 소음이 납니다.",
                      risk=0.01, bears_on=["c"], contradicts=["c"],
                      source_url=f"https://shop.example/review/{i}")
               for i in range(20)]

    shown = gather(claim, reviews, LabelMatcher(), 0.20, NoRiskScorer(),
                   source_may_quote=True)
    hidden = gather(claim, reviews, LabelMatcher(), 0.20, NoRiskScorer(),
                    source_may_quote=False)

    # 판정에 쓰는 값은 정책과 무관해야 한다
    assert shown.relevant == hidden.relevant == 20, "정책이 표본 수를 바꿨다"
    assert shown.hits == hidden.hits == 20, "정책이 판정 근거 수를 바꿨다"

    assert shown.quotes and shown.excerpt_policy == "verbatim", "허락했는데 인용이 없다"
    assert not hidden.quotes, "가리기로 했는데 원문이 실렸다"
    assert hidden.excerpt_policy == "withheld", hidden.excerpt_policy
    assert hidden.sources, "인용을 가렸으면 출처라도 가리켜야 한다"
    assert "정책상" in hidden.note, f"못 보여준다는 사실을 안 말한다: {hidden.note}"
    print("  ✓ 인용을 가려도 판정·표본은 그대로이고, 가렸다는 것을 말한다")


def check_tools_never_take_user_text() -> None:
    """
    **도구 인자에 사용자 문장이 없어야 한다.**

    처음에는 `ask_missing(query)` 로 받았다. 세 번 돌려 보니 세 번 다 모델이
    원문을 고쳐서 넘겼고, 두 번은 게임명이 빠져 **VRAM 12GB 하드 제약이 통째로
    사라졌다.** 그런데 에러는 안 난다 — 조건을 어긴 8GB 카드가 든 세트가
    그럴듯하게 나온다. 한 번은 예산까지 빠져 배분이 무너졌다.

    사용자 질문은 서버가 이미 갖고 있으므로 `bind()` 로 물린다. `rank()` 가
    판정을 못 받게 한 것과 같은 수다 — 받을 수 없으면 못 바꾼다.
    """
    from app.engine import tools

    specs = {t.tool_spec["name"]: t.tool_spec for t in tools.TOOLS}
    assert "ask_missing" in specs, list(specs)

    banned = {"query", "question", "text", "input", "user_query", "prompt"}
    for name, spec in specs.items():
        props = set(spec["inputSchema"]["json"].get("properties", {}))
        leaked = props & banned
        assert not leaked, f"{name} 이 사용자 문장을 인자로 받는다: {leaked}"
        assert spec.get("description"), f"{name}: 설명이 없으면 모델이 언제 부를지 모른다"

    assert not spec_props(specs, "ask_missing"), (
        "ask_missing 에 인자가 생겼다 — 사용자 입력이 모델을 거쳐 돌아올 통로다"
    )
    print(f"  ✓ 도구 {len(specs)}종 어디에도 사용자 문장을 넘기지 않는다")


def spec_props(specs: dict, name: str) -> set:
    return set(specs[name]["inputSchema"]["json"].get("properties", {}))


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
        check_semantic_matching_is_a_step,
        check_reviews_belong_to_the_part,
        check_high_risk_reviews_are_excluded,
        check_quotes_are_real,
        check_matcher_guardrails,
        check_tools_never_take_user_text,
        check_unscored_risk_is_never_clean,
        check_engine_knows_no_domain,
        check_excerpts_can_be_withheld,
        check_domains_are_listed_even_when_missing,
        check_screening_reports_zero,
        check_silent_failures_are_spoken,
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
