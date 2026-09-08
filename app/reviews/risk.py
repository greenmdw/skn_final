"""
조작 확률 매기기 — 리뷰 한 건이 심어진 것일 확률.

기획안 §9가 **AI 자리**로 표시한 셋 중 하나인데(3단계 조작 리뷰 확률) 코드에
자리가 없었다. 합성 소스는 스스로 점수를 붙이고 있었고, 실 리뷰가 들어오면
`risk` 가 기본값 0.0 이 되어 **20% 필터가 한 건도 안 거르는데 에러는 안 났다.**
목업 공개 화면의 약속 하나가 조용히 무력해지는 자리다.

    RISK_MODE=none (기본값) 점수를 매기지 않는다. 이미 붙어 있는 것만 쓴다
    RISK_MODE=llm           모델이 문체·맥락으로 매긴다. OPENAI_API_KEY 필요

기본값이 `none` 인 이유는 합성 데이터가 이미 점수를 들고 있어서다. 점수가 없는
리뷰가 섞이면 **거르지 않고 세어서 내보낸다**(`Evidence.unscored_risk`) —
못 잰 것을 "깨끗하다"로도 "조작이다"로도 처리하지 않는다.

[이진 판정을 하지 않는다]
기획안 §6-3: 개별 리뷰의 진위를 맞히는 사업(Fakespot·ReviewMeta)은 LLM 시대에
무너졌다. 우리는 진위를 목적이 아니라 수단으로 쓰므로 **확률만 매기고 판정은
임계값이 한다.** 모델에게 "조작이냐"고 묻지 않고 "확률이 얼마냐"고 묻는 이유다.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from pydantic import BaseModel, Field

from ..engine.schemas import Review

log = logging.getLogger(__name__)

RISK_MODE = os.environ.get("RISK_MODE", "none").lower()
RISK_BATCH = int(os.getenv("RISK_BATCH", "10"))
# 채점 모델은 `_model("risk")` 가 고른다 — 대조와 마찬가지로 호출량이 많아
# 자리별로 따로 지정할 수 있다(`RISK_MODEL` / `RISK_BEDROCK_MODEL`).


class RiskScorer(Protocol):
    name: str

    def score(self, reviews: list[Review]) -> None:
        """점수가 없는 리뷰에 `risk` 를 채운다. 제자리에서 고친다."""
        ...


class NoRiskScorer:
    """점수를 매기지 않는다. 이미 붙어 있는 것은 그대로 두고 없는 것은 없는 채로 둔다."""

    name = "none"

    def score(self, reviews: list[Review]) -> None:
        return


class _Score(BaseModel):
    review_id: str
    risk: float = Field(description="이 리뷰가 심어진(조작된) 것일 확률 0.0~1.0")
    why: str = Field(default="", description="그렇게 본 이유 한 구절")


class _Batch(BaseModel):
    scores: list[_Score] = Field(description="보낸 리뷰 하나당 정확히 하나씩")


RISK_SYSTEM = (
    "당신은 상품 리뷰가 **심어진 것(조작 리뷰)일 확률**을 매깁니다.\n"
    "- 조작이다/아니다로 단정하지 말고 **0.0~1.0 확률**로 답하세요. 경계는 흐립니다\n"
    "- 심어진 리뷰의 특징: 구체적 사용 경험 없이 칭찬만 있음, 제품명·기능을 부자연"
    "스럽게 반복, 단점이 형식적이거나 사소함, 다른 리뷰와 문장 구조가 비슷함\n"
    "- 짧다고 조작이 아니고, 길고 구체적이라고 진짜가 아닙니다. 요즘 조작 리뷰는 "
    "길고 구체적이며 사소한 불만까지 넣습니다\n"
    "- 판단이 어려우면 0.5 근처로 두세요. **모르는 것을 확신으로 바꾸지 마세요**\n"
    "- 보낸 리뷰 전부에 대해 하나씩, review_id 를 그대로 써서 답하세요"
)


class LLMRiskScorer:
    """
    모델이 조작 확률을 매긴다. 묶음으로 나눠 부른다.

    **점수가 이미 있는 리뷰는 건드리지 않는다.** 합성 데이터의 정답 라벨을
    덮어쓰면 채점(`scripts/eval_matcher.py`)의 정답이 사라진다.
    """

    name = "llm"

    def score(self, reviews: list[Review]) -> None:
        from strands import Agent

        from ..strands_agents import _model

        todo = [r for r in reviews if r.risk is None]
        if not todo:
            return
        by_id = {r.review_id: r for r in todo}

        for i in range(0, len(todo), RISK_BATCH):
            batch = todo[i:i + RISK_BATCH]
            agent = Agent(model=_model("risk"), system_prompt=RISK_SYSTEM)
            try:
                result = agent.structured_output(_Batch, _prompt(batch))
            except Exception as e:  # noqa: BLE001 — 한 묶음이 실패해도 나머지는 매긴다
                log.warning("조작 확률 묶음 실패(%d건): %s", len(batch), e)
                continue
            for sc in result.scores:
                r = by_id.get(sc.review_id)
                if r is None:
                    log.warning("보내지 않은 review_id 를 받았습니다: %s", sc.review_id)
                    continue
                # 범위를 벗어난 값은 버린다. 점수가 안 붙으면 "못 쟀다"로 남는다.
                if not 0.0 <= sc.risk <= 1.0:
                    log.warning("범위 밖 확률을 버립니다: %s = %s", sc.review_id, sc.risk)
                    continue
                r.risk = round(sc.risk, 4)


def _prompt(reviews: list[Review]) -> str:
    lines = ["아래 리뷰 각각이 심어진 것일 확률을 매기세요.", ""]
    lines += [f"[{r.review_id}] {r.text}" for r in reviews]
    return "\n".join(lines)


def build_scorer(mode: str | None = None) -> RiskScorer:
    return LLMRiskScorer() if (mode or RISK_MODE).lower() == "llm" else NoRiskScorer()
