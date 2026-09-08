"""
3단계 ③의 의미 대조 — *"이 리뷰 문장이 이 주장에 닿는가, 어긋나는가"*.

기획안 §9가 AI 자리라고 표시한 지점이고, §3이 *"이 기획의 심장"* 이라 부른 곳이다.
이 파일이 생기기 전까지 그 판정은 합성 라벨에 미리 들어 있었다 — 파이프라인은
끝까지 돌았지만 대조하는 일 자체가 코드에 없었다
([`decisions/0008`](../../docs/decisions/0008-리뷰-소스-기본값을-합성으로-둔다.md)
의 "가장 큰 함정").

    MATCH_MODE=label  (기본값) 합성 라벨을 읽는다. 키가 필요 없다
    MATCH_MODE=llm             모델이 문장을 실제로 읽는다. OPENAI_API_KEY 필요

**두 구현이 같은 형(`list[ReviewJudgment]`)을 낸다.** 그래서 라벨을 정답으로 두고
LLM 을 채점할 수 있다 — `scripts/eval_matcher.py`. 합성이라 공짜로 얻은 라벨의
진짜 값이 이것이다.

[판정은 여전히 룰이 한다]
모델이 정하는 것은 *리뷰 한 건이 주장에 닿는지·어긋나는지*까지다. 표본이 몇 건
이상이어야 판정하는지, 어긋난 비율 얼마부터 반증인지는 `verify.py` 의 상수다.
모델이 "반증입니다"라고 말할 자리를 만들지 않았다.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Protocol

from pydantic import BaseModel, Field

from .schemas import Claim, Evidence, Review, ReviewJudgment

log = logging.getLogger(__name__)

MATCH_MODE = os.environ.get("MATCH_MODE", "label").lower()

# 주장 하나에 대해 모델에게 보낼 리뷰 수 상한. 비용과 지연이 여기서 정해진다.
# 넘치면 앞에서부터 자르고 몇 건을 못 봤는지 근거에 남긴다 — 조용히 자르면
# "표본 부족"과 "우리가 안 봤다"가 구분되지 않는다.
#
# **대조기가 들고 있는 값이다.** 상한이 있는 이유가 모델 호출 비용이라, 라벨
# 대조기에 걸면 표본만 잃고 얻는 게 없다(`LabelMatcher.max_reviews = None`).
MATCH_MAX_REVIEWS = int(os.getenv("MATCH_MAX_REVIEWS", "200"))

# 한 번의 호출에 넣는 리뷰 수.
#
# 20 에서 10 으로 내렸다. 채점(`scripts/eval_matcher.py`)에서 재현율이 0.42~0.81 로
# 낮게 나왔는데 정밀도는 1.00 이었다 — 틀리게 판정한 게 아니라 **답을 아예 안 준**
# 것이다. 20건을 보내면 모델이 12~15건만 답하고 끝낸다. 묶음이 작을수록 덜 빠진다.
MATCH_BATCH = int(os.getenv("MATCH_BATCH", "10"))

# 답이 안 온 리뷰를 다시 묻는 횟수. 그래도 안 오면 "닿지 않음"으로 둔다.
MATCH_RETRIES = int(os.getenv("MATCH_RETRIES", "1"))


class Matcher(Protocol):
    name: str

    def match(self, claim: Claim, reviews: list[Review]) -> list[ReviewJudgment]:
        ...


# ── 라벨 대조 (기본값) ───────────────────────────────────────────────────────
class LabelMatcher:
    """
    합성 데이터의 정답 라벨을 그대로 읽는다.

    **이건 의미 대조가 아니다.** 실데이터에는 이 라벨이 없다. 키 없이 검사와
    데모가 돌게 하려고 두는 것이고, 동시에 LLM 을 채점할 정답 역할을 한다.
    """

    name = "label"
    max_reviews = None      # 공짜다. 자를 이유가 없다

    def match(self, claim: Claim, reviews: list[Review]) -> list[ReviewJudgment]:
        out = []
        for r in reviews:
            bears = claim.claim_id in r.bears_on
            out.append(ReviewJudgment(
                review_id=r.review_id,
                bears_on=bears,
                contradicts=bears and claim.claim_id in r.contradicts,
                quote=r.text if bears else "",
            ))
        return out


# ── 모델 대조 ────────────────────────────────────────────────────────────────
class _Batch(BaseModel):
    judgments: list[ReviewJudgment] = Field(
        description="보낸 리뷰 하나당 정확히 하나씩. review_id 는 받은 것을 그대로 쓸 것"
    )


MATCH_SYSTEM = (
    "당신은 상품 리뷰가 제조사의 스펙 주장과 어긋나는지 판정합니다.\n"
    "- 각 리뷰에 대해 두 가지만 정하세요: (1) 이 주장을 **언급하거나 다루는가**"
    "(bears_on) (2) 다룬다면 주장과 **어긋나는가**(contradicts)\n"
    "- 주장을 다루지 않으면 bears_on=false 입니다. 이때 contradicts 는 항상 false 입니다\n"
    "- **다른 부품이나 다른 항목에 대한 언급은 닿는 것이 아닙니다.** 그래픽카드 "
    "온도 주장에 'CPU 온도가 높다'는 리뷰는 bears_on=false 입니다\n"
    "- 주장을 다루면서 어긋나지 않으면 bears_on=true, contradicts=false 입니다\n"
    "- quote 에는 판단 근거가 된 **리뷰 원문 안의 구절을 그대로** 옮기세요. "
    "요약하거나 바꿔 쓰지 마세요\n"
    "- 보낸 리뷰 전부에 대해 하나씩, review_id 를 그대로 써서 답하세요"
)


class LLMMatcher:
    """
    모델이 리뷰를 실제로 읽는다. 묶음으로 나눠 부른다.

    **모델이 지어낼 수 있는 자리를 셋 막았다.** 셋 다 조용히 틀리는 종류다.

    1. 보내지 않은 `review_id` 는 버린다 (모델이 만든 항목)
    2. 답이 안 온 리뷰는 **닿지 않음**으로 둔다. 빠뜨린 것을 "어긋남"으로 세면
       표본이 조용히 부풀고, 임계값이 그 위에서 돈다
    3. 원문에 없는 `quote` 는 지운다 — `report.py` 의 `_verify()` 와 같은 종류의
       가드레일이다. 인용이 근거로 쓰이는데 지어낸 인용이면 근거가 아니다
    """

    name = "llm"
    max_reviews = MATCH_MAX_REVIEWS
    unanswered = 0          # 마지막 대조에서 끝내 답이 없던 건수

    def match(self, claim: Claim, reviews: list[Review]) -> list[ReviewJudgment]:
        from strands import Agent

        from ..strands_agents import _model

        by_id = {r.review_id: r for r in reviews}
        got: dict[str, ReviewJudgment] = {}

        pending = list(reviews)
        for attempt in range(MATCH_RETRIES + 1):
            if not pending:
                break
            size = max(1, MATCH_BATCH // (attempt + 1))
            for i in range(0, len(pending), size):
                batch = pending[i:i + size]
                agent = Agent(model=_model(), system_prompt=MATCH_SYSTEM)
                try:
                    result = agent.structured_output(_Batch, _prompt(claim, batch))
                except Exception as e:  # noqa: BLE001 — 한 묶음이 실패해도 나머지는 판정한다
                    log.warning("대조 묶음 실패(%d건): %s", len(batch), e)
                    continue
                got.update(accept(result.judgments, by_id, claim))
            pending = [r for r in pending if r.review_id not in got]
            if pending:
                log.info("답이 안 온 리뷰 %d건을 다시 묻습니다(%d차)", len(pending), attempt + 2)

        # 끝내 답이 없으면 **닿지 않음**으로 둔다. 빠뜨린 것을 "어긋남"으로 세면
        # 표본이 조용히 부풀고 임계값이 그 위에서 돈다.
        self.unanswered = len(pending)
        if pending:
            log.warning("리뷰 %d건은 판정을 받지 못했습니다 — 닿지 않음으로 둡니다", len(pending))

        return [got.get(r.review_id,
                        ReviewJudgment(review_id=r.review_id, bears_on=False,
                                       contradicts=False))
                for r in reviews]


_NUMERIC = re.compile(r"\d")


def accept(judgments: list[ReviewJudgment], by_id: dict[str, Review],
           claim: Claim | None = None) -> dict[str, ReviewJudgment]:
    """
    모델이 낸 판정에서 **믿을 수 있는 것만** 남긴다.

    모델을 부르지 않고도 검사할 수 있게 순수 함수로 뽑아 뒀다 — 여기서 막는
    넷이 전부 조용히 틀리는 종류라 검사가 없으면 새는지도 모른다.

    [넷째: 수치 주장에는 수치가 있는 인용을 요구한다]
    채점에서 나온 것이다. SSD *"연속 쓰기 5,000MB/s"* 에 대해 모델이 40건 중
    12건을 "닿는다"고 했는데 정답은 3건이었다. 늘어난 것들은 *"쓰기 속도는 공식
    스펙만 보고 샀습니다"* 처럼 **화제는 같지만 실측을 말하지 않는** 문장이다.

    이게 왜 비싼가: 그 주장은 표본이 얇아 `NO_EVIDENCE` 로 끝나야 하는 자리인데,
    닿는 표본이 12건으로 부풀면 임계값을 넘어 `PARTLY` 가 된다. **"모르는 것을
    모른다고 말한다"가 깨지는 지점이 하필 그 원칙이 사는 유일한 자리다.**

    그래서 주장에 수치가 있으면 근거 인용에도 수치를 요구한다. 인용을 아예 안
    준 판정은 건드리지 않는다 — 못 재는 것을 틀렸다고 할 수는 없다.
    """
    numeric = bool(claim and _NUMERIC.search(claim.text))

    out: dict[str, ReviewJudgment] = {}
    for j in judgments:
        r = by_id.get(j.review_id)
        if r is None:
            log.warning("보내지 않은 review_id 를 받았습니다: %s", j.review_id)
            continue
        if j.quote and j.quote not in r.text:
            log.warning("원문에 없는 인용을 지웁니다: %s", j.review_id)
            j.quote = ""
        if numeric and j.bears_on and j.quote and not _NUMERIC.search(j.quote):
            log.info("수치 주장인데 인용에 수치가 없어 닿지 않음으로 둡니다: %s", j.review_id)
            j.bears_on = False
        if not j.bears_on:
            j.contradicts = False
        out[j.review_id] = j
    return out


def _prompt(claim: Claim, reviews: list[Review]) -> str:
    lines = [
        f"대상: {claim.subject}",
        f"주장({claim.source}): \"{claim.text}\"",
        "",
        "아래 리뷰 각각이 이 주장에 닿는지, 닿는다면 어긋나는지 판정하세요.",
        "",
    ]
    lines += [f"[{r.review_id}] {r.text}" for r in reviews]
    return "\n".join(lines)


# ── 근거 만들기 ──────────────────────────────────────────────────────────────
def gather(claim: Claim, reviews: list[Review], matcher: Matcher,
           risk_threshold: float) -> Evidence:
    """
    리뷰 묶음 하나에서 주장 하나의 근거를 만든다.

    **조작 확률이 임계 이상인 리뷰는 대조에 넣지 않는다.** 목업 공개 화면의
    약속이다 — *"조작 확률 20% 이상인 리뷰는 대조 표본에서 제외. 삭제하지 않고
    별도 보관한다."* 지우지 않고 세어서 `excluded_high_risk` 로 내보낸다.
    """
    kept = [r for r in reviews if r.risk < risk_threshold]
    excluded = len(reviews) - len(kept)

    truncated = 0
    cap = getattr(matcher, "max_reviews", None)
    if cap and len(kept) > cap:
        truncated = len(kept) - cap
        kept = kept[:cap]

    judgments = matcher.match(claim, kept)
    by_id = {r.review_id: r for r in kept}

    samples: dict[str, int] = {}
    for r in kept:
        samples[r.kind] = samples.get(r.kind, 0) + 1

    relevant = [j for j in judgments if j.bears_on]
    hits = [j for j in relevant if j.contradicts]

    quotes = [j.quote for j in (hits or relevant) if j.quote][:3]
    if not quotes:
        quotes = [by_id[j.review_id].text for j in (hits or relevant)[:3] if j.review_id in by_id]

    return Evidence(
        samples=samples,
        relevant=len(relevant),
        hits=len(hits),
        note=_note(len(relevant), len(hits), truncated),
        quotes=quotes,
        excluded_high_risk=excluded,
    )


def _note(relevant: int, hits: int, truncated: int) -> str:
    """
    근거 한 줄. **숫자에서만 만든다** — 손으로 쓴 문구를 두지 않는다.

    예전에는 팩이 "214건 중 47건이 80°C 이상을 언급" 같은 문장을 들고 있었다.
    읽기는 좋지만 대조가 실제로 낸 숫자와 어긋나도 아무도 모른다. 구체적인
    내용은 이제 `Evidence.quotes` 의 실제 인용이 맡는다.
    """
    if truncated:
        tail = f" (상한을 넘은 {truncated}건은 대조하지 않았습니다)"
    else:
        tail = ""
    if hits:
        return f"{relevant}건이 이 주장에 닿고 그중 {hits}건이 어긋납니다{tail}."
    if relevant:
        return f"{relevant}건을 대조했고 어긋나는 사례가 없습니다{tail}."
    return f"이 주장에 닿는 리뷰가 없습니다{tail}."


def build_matcher(mode: str | None = None) -> Matcher:
    return LLMMatcher() if (mode or MATCH_MODE).lower() == "llm" else LabelMatcher()
