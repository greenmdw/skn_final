"""
`REVIEW_SOURCE=synthetic` (기본값) — 라벨이 붙은 합성 리뷰를 **문장으로** 만든다.

[왜 이게 기본값인가]
9/7 23시에 네이버·카카오 둘 다 리뷰 API 가 없다는 것이 확인됐다. 배경과 대가는
[`decisions/0008`](../../docs/decisions/0008-리뷰-소스-기본값을-합성으로-둔다.md).

[집계가 아니라 문장을 준다]
처음에는 이 파일이 `Evidence`(표본·닿는 수·어긋난 수)를 바로 돌려줬다. 그러면
*"이 문장이 이 주장에 닿는가"* 를 판정하는 일이 코드에 아예 없다 — 3단계의 심장이
데이터에 미리 들어 있는 셈이라 파이프라인이 도는 것을 보고 됐다고 착각하게 된다.
0008 이 가장 큰 함정으로 적어 둔 것이 정확히 이것이라, 소스는 **문장만** 주고
판정은 `app/engine/match.py` 가 한다.

[라벨의 값은 두 가지다]
정답 라벨(`bears_on`·`contradicts`)은 키 없이 도는 `LabelMatcher` 를 위한 것이자,
**`LLMMatcher` 를 채점하기 위한 것**이다. 두 번째가 더 중요하다 — 합성이라 라벨이
공짜인데, 그 공짜 라벨이 의미 대조의 정확도를 재는 유일한 자
(`scripts/eval_matcher.py`)가 된다.

[일부러 헷갈리게 만들었다]
`FILLER` 에 온도·속도·소음 같은 낱말이 들어 있지만 그 주장에 대한 것은 아닌
문장을 섞었다("CPU 온도가 높아 고민인데 이건 별개 문제겠죠"). 낱말만 보는 대조는
여기서 틀린다. 그게 없으면 채점이 언제나 만점이라 아무것도 못 잰다.

**합성임을 숨기지 않는다** — `disclosure()` 가 응답에 실려 나간다.
"""

from __future__ import annotations

import random

from ..engine.schemas import Review

# 조작 확률을 왼쪽으로 크게 치우치게 만드는 지수. 실제 리뷰의 조작 비율이
# 이렇다는 주장이 아니라, 분포로 보여준다는 §7의 형식을 데모에서 쓰기 위한 값이다.
SKEW = 16

# 임계값을 넘어 대조에서 빠지는 리뷰를 이 비율만큼 더 만든다. 목업 공개 화면이
# "733건 중 62건(8.5%) 제외"라고 적었다.
EXCLUDED_RATIO = 0.09

BUCKETS = ("0-20%", "20-40%", "40-60%", "60-80%", "80-100%")


class SyntheticReviews:
    """
    품목별 리뷰 묶음을 만든다. 같은 품목을 두 번 물어도 같은 것이 나온다.

    실행할 때마다 리뷰가 바뀌면 판정도 바뀌고 발표에서 못 쓴다.
    """

    name = "synthetic"
    # 우리가 지어낸 문장이라 인용해도 된다. **실소스 어댑터는 False 가 기본이어야
    # 한다** — 9/8 17시 방침(리뷰 원문을 그대로 내보내지 않는다).
    may_quote = True

    def __init__(self, pools: dict, phrases: dict, filler: list[str],
                 threshold: float = 0.20) -> None:
        self._pools = pools
        self._phrases = phrases
        self._filler = filler
        self.threshold = threshold
        self._cache: dict[str, list[Review]] = {}

    # ── ReviewSource ────────────────────────────────────────────────────
    def fetch(self, part_code: str) -> list[Review]:
        """
        그 품목의 리뷰 **전부**를 돌려준다 — 조작 확률이 높은 것도 포함한다.

        거르는 것은 소스가 아니라 대조하는 쪽 일이다. 소스가 미리 걸러 버리면
        "몇 건을 왜 뺐는지"를 화면에 공개할 수 없는데, 그 공개가 공개 화면의
        약속 중 하나다.
        """
        if part_code in self._cache:
            return self._cache[part_code]

        spec = self._pools.get(part_code)
        if spec is None:
            return []

        rng = random.Random(part_code)
        reviews: list[Review] = []
        retained: dict[str, list[Review]] = {}

        for kind, keep in spec["retained"].items():
            pool = []
            for i in range(keep):
                r = Review(review_id=f"{part_code}:{kind}:{i:04d}", part_code=part_code,
                           kind=kind, text="",
                           # 대조에 남는 것 — 임계값 아래로만 나온다
                           risk=round(rng.random() ** SKEW * self.threshold, 4))
                pool.append(r)
                reviews.append(r)
            retained[kind] = pool

            for i in range(round(keep * EXCLUDED_RATIO)):
                reviews.append(Review(
                    review_id=f"{part_code}:{kind}:x{i:03d}", part_code=part_code,
                    kind=kind, text="",
                    # 임계값 바로 위에 몰리게 — 목업 분포도 오른쪽으로 갈수록 준다
                    risk=round(self.threshold + (1 - self.threshold) * rng.random() ** 3, 4)))

        # 정답 라벨은 **대조에 남는 것**에만 붙인다. 목업의 "대조 표본" 칸이
        # 필터를 통과한 뒤의 수이기 때문이다.
        for claim_id, c in spec["claims"].items():
            cands = [r for kind in c["in"] for r in retained.get(kind, [])]
            for j, r in enumerate(cands[: c["relevant"]]):
                r.bears_on.append(claim_id)
                if j < c["hits"]:
                    r.contradicts.append(claim_id)

        for r in reviews:
            r.text = self._compose(r)

        self._cache[part_code] = reviews
        return reviews

    def risk_distribution(self) -> dict[str, int]:
        """
        지금까지 읽은 리뷰 전체의 조작 확률 분포. 구간별 건수만 돌려준다.

        점수 하나로 합치지 않는 이유는 기획안 §6-3에 있다 — 개별 리뷰의 진위를
        맞히는 사업(Fakespot·ReviewMeta)은 LLM 시대에 무너졌고, 우리는 진위를
        목적이 아니라 수단으로 쓴다.
        """
        out = {b: 0 for b in BUCKETS}
        for reviews in self._cache.values():
            for r in reviews:
                if r.risk is None:      # 못 잰 것은 분포에 넣지 않는다
                    continue
                out[BUCKETS[min(int(r.risk * 5), 4)]] += 1
        return out

    def disclosure(self) -> str:
        return (
            "이 판정에 쓰인 리뷰는 합성 데이터입니다. 조작 리뷰의 정답 라벨이 "
            "필요해 합성했고, 실제 상품의 리뷰가 아닙니다."
        )

    # ── 내부 ────────────────────────────────────────────────────────────
    def _compose(self, review: Review) -> str:
        """
        리뷰 본문. 닿는 주장마다 문장 하나씩 붙이고 잡담을 섞는다.

        조작 리뷰(임계값 위)에는 **칭찬만** 심는다 — 기획안 §6-3의 관찰대로
        "조작 리뷰를 심는 쪽은 칭찬을 심지, 같은 불만을 41건 심지 않는다".
        """
        rng = random.Random(review.review_id)
        parts: list[str] = []

        for claim_id in review.bears_on:
            phrases = self._phrases.get(claim_id, {})
            pool = phrases.get("against" if claim_id in review.contradicts else "for", [])
            if pool:
                parts.append(rng.choice(pool))

        if not parts:
            if review.risk >= self.threshold:
                praise = [s for ph in self._phrases.values() for s in ph.get("for", [])]
                parts.append(rng.choice(praise or self._filler))
            parts.append(rng.choice(self._filler))

        parts.append(rng.choice(self._filler))
        return " ".join(parts)
