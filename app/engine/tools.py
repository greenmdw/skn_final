"""
Strands `@tool` — 6단계 각각을 에이전트가 부를 수 있게 노출한다.

`agent_tools.py` 가 협상 쪽에서 한 것과 같은 일이고, 이유도 같다. 심사 기준
1번이 *"a working, **non-trivial** implementation"* 을 묻는데, 어댑터만 바꾼
구현으로는 낮게 받는다(`docs/해커톤_요건_대조.md` §3). 기획안 §14도 대응을
*"에이전트가 도구를 스스로 골라 부른다. 6단계가 각각 도구"* 로 적어 뒀다.

**새 로직이 없다.** 전부 `pipeline.py` 의 함수를 감싸기만 한다 — 판정은 여전히
룰이 하고, 모델이 정하는 것은 *무엇을 언제 부를지*다. 그래야 "소켓이 안 맞는데
맞다고 함"이 모델 쪽에서 생길 자리가 없다.

**사용자 입력과 팩은 모듈 전역으로 고정한다. 도구 인자로 받지 않는다.**

팩이 인자면 모델이 도메인을 고르게 되는데 도메인은 모델이 정할 것이 아니다.
사용자 질문은 더 나쁘다 — 처음에는 `ask_missing(query)` 로 받았는데, 세 번
돌려 보니 **세 번 다 모델이 원문을 고쳐서 넘겼다.**

    원문   "〈오르카 프로토콜〉 QHD 상옵으로 돌리고 싶어요. 예산 120만 원이고 …"
    1회차  "QHD 상옵으로 돌리고 싶어요. 예산 120만 원이고 …"        게임명 소실
    2회차  "오르카 프로토콜 QHD 상옵을 돌리기 위한 부품 추천을 위해 …"
    3회차  "QHD 상옵으로 돌아갈 PC 부품 추천을 위해 필요한 정보를 …"  게임·예산 소실

게임명이 빠지면 2단계의 외부 사실이 안 붙고 **VRAM 12GB 하드 제약이 사라진다.**
그런데 에러는 안 난다 — 파이프라인은 끝까지 돌고, 조건을 어긴 8GB 카드가 든
세트가 그럴듯하게 나온다. 예산까지 빠지면 배분이 통째로 무너진다.

사용자 질문은 서버가 이미 갖고 있다. 모델을 거쳐 돌아올 이유가 없고, 거치면
바뀐다. **모델이 정할 것은 언제 부를지이지 사용자가 무엇을 말했는지가 아니다.**
"""

from __future__ import annotations

from strands import tool

from . import pipeline
from .schemas import Requirement

_PACK = None
_QUERY = ""
_STATE: dict = {}


def bind(pack, query: str = "", answers: dict | None = None) -> None:
    """
    요청 하나가 시작될 때 팩·사용자 질문·되묻기 답을 물린다.

    도구들은 여기 물린 것만 본다. 모델이 바꿔 넣을 수 있는 통로를 두지 않는다.
    """
    global _PACK, _QUERY
    _PACK = pack
    _QUERY = query
    _STATE.clear()
    if answers:
        _STATE["known"] = dict(answers)


def state() -> dict:
    """도구가 만든 중간 산출물. 엔진이 응답을 조립할 때 읽는다."""
    return _STATE


@tool
def ask_missing() -> dict:
    """
    사용자 입력에서 아는 것을 뽑고, 아직 모르는 것을 되묻을 목록으로 돌려준다.

    추천을 내기 전에 가장 먼저 부른다. `needs_input` 이 비어 있지 않으면
    추천을 만들지 말고 그 질문을 사용자에게 돌려주어야 한다.

    **인자가 없다.** 사용자가 쓴 문장은 서버가 이미 갖고 있다 — 옮겨 적지 말 것.
    """
    known, needs = pipeline.step1_checklist(_PACK, _QUERY, _STATE.get("known"))
    _STATE["known"] = known
    _STATE["needs_input"] = needs
    return {"known": known, "needs_input": [n.model_dump() for n in needs]}


@tool
def collect_requirements() -> list[dict]:
    """
    아는 것에 **외부 사실**(게임사 공개 권장 사양)을 붙여 하드 제약으로 바꾼다.

    `ask_missing` 다음에 부른다. 여기 나오는 값은 전부 출처와 기준 시점을
    달고 나온다 — 모델이 사양을 기억으로 답하면 안 되는 자리다.
    """
    reqs = pipeline.step2_requirements(_PACK, _STATE.get("known", {}))
    _STATE["requirements"] = reqs
    return [r.model_dump() for r in reqs]


@tool
def build_set() -> dict:
    """
    하드 제약을 걸어 후보를 거르고 호환성을 맞춰 부품 세트를 짠다.

    `collect_requirements` 다음에 부른다. 소켓·전력·길이 판정은 전부 룰이므로
    결과를 그대로 신뢰해도 된다.
    """
    reqs: list[Requirement] = _STATE.get("requirements", [])
    budget = int(_STATE.get("known", {}).get("budget") or 0)
    chosen = pipeline.rank(_PACK, reqs, budget, _STATE.get("known", {}))
    _STATE["chosen"] = chosen
    return {"budget": budget,
            "parts": [{"category": p["category"], "code": p["code"],
                       "name": p["name"], "price": p["price"]} for p in chosen]}


@tool
def verify_claims_against_reviews() -> list[dict]:
    """
    세트에 든 품목들의 **제조사 주장을 리뷰와 대조**해 판정한다.

    `build_set` 다음에 부른다. 이 프로젝트의 핵심 단계다. 판정은 네 가지이고
    (확인·부분 확인·반증·근거 없음) 표본이 부족하면 반드시 "근거 없음"이다 —
    **부족한 표본으로 확인했다고 말하지 말 것.**
    """
    verdicts = pipeline.step3_verify(_PACK, _STATE.get("chosen", []))
    _STATE["verdicts"] = verdicts
    return [{"claim_id": cv.claim.claim_id, "subject": cv.claim.subject,
             "text": cv.claim.text, "verdict": cv.verdict.value,
             "samples": cv.evidence.samples, "relevant": cv.evidence.relevant,
             "hits": cv.evidence.hits, "note": cv.evidence.note}
            for cv in verdicts]


@tool
def apply_verdicts_to_set() -> dict:
    """
    반증 판정을 세트에 반영한다 — 필요한 품목을 **추가**하거나 경고를 단다.

    `verify_claims_against_reviews` 다음에 부른다. **반증됐다고 품목을 빼지
    않는다.** 대안이 없으면 경고만 달고 목록에 남긴다.
    """
    lines, verdicts = pipeline.step4_optimize(
        _PACK, _STATE.get("chosen", []), _STATE.get("verdicts", []),
        int(_STATE.get("known", {}).get("budget") or 0),
        _STATE.get("requirements", []))
    # 구성이 바뀌면 판정도 다시 나온다 — 옛 판정을 그대로 두면 화면이 세트에
    # 없는 품목의 주장을 보여주게 된다.
    _STATE["set"] = lines
    _STATE["verdicts"] = verdicts
    return {"set": [ln.model_dump() for ln in lines],
            "spent": sum(ln.price for ln in lines)}


TOOLS = [ask_missing, collect_requirements, build_set,
         verify_claims_against_reviews, apply_verdicts_to_set]
