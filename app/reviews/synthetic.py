"""
`REVIEW_SOURCE=synthetic` (기본값) — 라벨이 붙은 합성 리뷰.

[왜 이게 기본값인가]
9/7 23시에 네이버·카카오 둘 다 리뷰 API 가 없다는 것이 확인됐다. 3단계가
데이터원 없이 남았는데 3단계는 이 기획의 심장이라, 소스가 없으면 파이프라인이
끝까지 못 돈다. `CATALOG_SOURCE=snapshot` 이 키 없이 실데이터로 도는 것과 같은
자리에 이걸 둔다 — **아무것도 설정하지 않아도 엔진 전체가 돈다.**

기획안 §11이 이미 이 결론을 적어 뒀다: *"8일 안의 현실안: 카탈로그·외부
사실·공공데이터는 실데이터, 리뷰는 합성 + 소량 실데이터. 조작 리뷰 판별은 정답
라벨이 필요한데 합성이면 라벨이 공짜다."*

**합성임을 숨기지 않는다** — 같은 문단의 단서이고, `disclosure()` 가 응답에
그대로 실려 나간다. 발표에서 *"심어 놓은 조작 리뷰 200건 중 187건을 잡았다"*
가 쓸 수 있는 숫자가 되는 것은 숨기지 않을 때뿐이다.

[라벨은 팩이 준다]
이 파일은 어떤 도메인인지 모른다. 주장별 라벨(표본·닿는 수·어긋난 수)은
`DomainPack` 이 넘겨준다 — 주장의 주인이 팩이므로 그 주장이 합성 세계에서
참인지도 팩이 안다. 라벨이 없는 주장은 claim_id 로 결정적으로 생성한다.
"""

from __future__ import annotations

import random

from ..engine.schemas import Claim, Evidence

# 조작 확률 분포를 왼쪽으로 크게 치우치게 만드는 지수. 균등난수 r 에 대해
# r**SKEW 를 쓰면 약 90% 가 0.2 미만으로 떨어진다 — 목업의 733건 중 671건(91.5%)
# 과 같은 모양이다. 실제 리뷰의 조작 비율이 이렇다는 주장이 아니라, **분포로
# 보여준다**는 §7의 형식을 데모에서 그대로 쓰기 위한 값이다.
SKEW = 16

BUCKETS = ("0-20%", "20-40%", "40-60%", "60-80%", "80-100%")


class SyntheticReviews:
    """
    라벨이 붙은 합성 리뷰 소스.

    `labels` 는 `{claim_id: {"samples": {...}, "relevant": int, "hits": int,
    "note": str}}` 형태다. 팩이 준다.
    """

    name = "synthetic"

    def __init__(self, labels: dict[str, dict] | None = None) -> None:
        self._labels = labels or {}
        # 대조에 실제로 쓴 리뷰 수. risk_distribution() 이 이 값으로 분포를 만든다.
        self._compared = 0

    # ── ReviewSource ────────────────────────────────────────────────────
    def evidence_for(self, claim: Claim) -> Evidence:
        label = self._labels.get(claim.claim_id)
        if label is None:
            label = self._synthesize(claim)
        ev = Evidence(
            samples=dict(label["samples"]),
            relevant=label["relevant"],
            hits=label["hits"],
            note=label.get("note", ""),
        )
        self._compared += ev.total
        return ev

    def risk_distribution(self) -> dict[str, int]:
        """
        대조에 쓴 리뷰 전체의 조작 확률 분포. 구간별 건수만 돌려준다.

        점수 하나로 합치지 않는 이유는 기획안 §6-3에 있다 — 개별 리뷰의 진위를
        맞히는 사업(Fakespot·ReviewMeta)은 LLM 시대에 무너졌고, 우리는 진위를
        목적이 아니라 수단으로 쓴다. *"리뷰 하나가 진짜인지 몰라도, 312건 중
        41건이 같은 불만을 말하면 주장은 흔들린다."*
        """
        rng = random.Random(20260908)
        out = {b: 0 for b in BUCKETS}
        for _ in range(self._compared):
            risk = rng.random() ** SKEW
            idx = min(int(risk * 5), 4)
            out[BUCKETS[idx]] += 1
        return out

    def disclosure(self) -> str:
        return (
            "이 판정에 쓰인 리뷰는 합성 데이터입니다. 조작 리뷰의 정답 라벨이 "
            "필요해 합성했고, 실제 상품의 리뷰가 아닙니다."
        )

    # ── 내부 ────────────────────────────────────────────────────────────
    def _synthesize(self, claim: Claim) -> dict:
        """
        라벨이 없는 주장을 위한 폴백. claim_id 로 seed 를 잡아 **결정적**이다.

        데모가 실행할 때마다 판정이 바뀌면 발표에서 못 쓴다.
        """
        rng = random.Random(claim.claim_id)
        reviews = rng.randint(40, 260)
        qa = rng.randint(0, 30)
        relevant = int(reviews * rng.uniform(0.05, 0.8))
        hits = int(relevant * rng.choice([0.0, 0.0, 0.06, 0.12, 0.25]))
        return {
            "samples": {"리뷰": reviews, "QA": qa} if qa else {"리뷰": reviews},
            "relevant": relevant,
            "hits": hits,
            "note": f"{relevant}건이 이 주장에 닿고 그중 {hits}건이 어긋납니다.",
        }
