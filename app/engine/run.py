"""
추천 엔진 진입점 — `RECOMMEND_MODE` 로 룰/Strands 를 전환한다.

    rule    (기본값) 1~5단계를 순서대로 부른다. 키가 필요 없다
    strands 에이전트가 도구를 스스로 골라 부른다. OPENAI_API_KEY 필요

기본값이 `rule` 인 이유는 `NEGOTIATOR_MODE` 와 같다 — 검사가 키 없이 돌아야
하고, 데모 당일 API 가 흔들려도 같은 화면이 나와야 한다. **두 경로가 같은
`pipeline.py` 함수를 쓴다.** 도구는 그 함수를 감싸기만 하므로 모드가 달라도
판정이 달라지지 않는다. 달라지는 것은 *순서를 누가 정하는가* 뿐이다.

[제출 전에 확인할 것]
`strands` 경로의 모델 왕복은 아직 안 돌려 봤다(키 없음). 협상·어시스턴트와
같은 상태이고, `docs/해커톤_요건_대조.md` §6의 1번 항목이 이것이다.
"""

from __future__ import annotations

import os

from ..reviews import build_source
from . import pipeline
from .schemas import Recommendation

RECOMMEND_MODE = os.environ.get("RECOMMEND_MODE", "rule").lower()

SYSTEM = (
    "당신은 PC 부품 추천 엔진을 운영합니다. 도구로만 판단하세요.\n"
    "- 순서: ask_missing → collect_requirements → build_set → "
    "verify_claims_against_reviews → apply_verdicts_to_set\n"
    "- **도구에 사용자 문장을 옮겨 적지 마세요.** 서버가 이미 갖고 있습니다\n"
    "- ask_missing 의 needs_input 이 비어 있지 않으면 **거기서 멈추고** 무엇을 "
    "물어야 하는지만 답하세요. 답을 지어내 진행하지 마세요\n"
    "- 부품 사양·가격·호환성·리뷰 건수를 기억으로 답하지 마세요. 전부 도구에서 옵니다\n"
    "- 표본이 부족한 주장은 '확인'이 아니라 '근거 없음'입니다. 확인했다고 쓰지 마세요\n"
    "- 반증된 품목을 목록에서 빼지 마세요. 경고를 달아 남깁니다"
)


def _notices(requirements, budget: int, spent: int, verdicts) -> list[str]:
    """
    엔진이 화면·사용자에게 **반드시** 알려야 하는 것. 비어 있는 것이 정상이다.

    셋 다 예전에는 조용히 지나갔다 — 결과는 그럴듯하게 나오고 어디에도 사실이
    적히지 않았다. 8개 시나리오를 돌려 보고서야 보였다.
    """
    out: list[str] = []

    if not [r for r in requirements if r.hard]:
        out.append(
            "외부 사실을 찾지 못해 하드 제약 없이 추천했습니다. "
            "조건을 걸지 않았으므로 이 세트는 요구사항을 만족한다고 보증하지 않습니다."
        )

    if budget and spent > budget:
        out.append(
            f"예산 {budget:,}원 안에 들어오는 조합을 찾지 못했습니다. "
            f"이 세트는 {spent - budget:,}원 초과입니다."
        )

    unscored = sum(cv.evidence.unscored_risk for cv in verdicts)
    if unscored:
        out.append(
            f"조작 확률을 재지 못한 리뷰 {unscored}건이 대조 표본에 섞여 있습니다. "
            "이 결과에는 '조작 확률 20% 이상을 걸렀다'가 성립하지 않습니다."
        )

    return out


def _pack(domain: str):
    if domain == "pc":
        from .packs.pc import pack

        return pack
    raise ValueError(f"모르는 도메인입니다: {domain!r}")


def recommend(query: str, domain: str = "pc", answers: dict | None = None,
              mode: str | None = None) -> Recommendation:
    """질문 하나를 6단계에 통과시키고 `Recommendation` 을 만든다."""
    pack = _pack(domain)
    mode = (mode or RECOMMEND_MODE).lower()
    if mode == "strands":
        return _run_strands(pack, query, answers, domain)
    return _run_rule(pack, query, answers, domain)


def _run_rule(pack, query: str, answers: dict | None, domain: str) -> Recommendation:
    known, needs = pipeline.step1_checklist(pack, query, answers)

    # 되묻기가 남아 있으면 **추천을 만들지 않는다.** 모르는 채로 세트를 짜면
    # 1단계가 하는 일("무엇을 모르는지 아는 것")이 사라진다.
    if needs:
        return Recommendation(domain=domain, needs_input=needs,
                              budget=int(known.get("budget") or 0), mode="rule")

    budget = int(known.get("budget") or 0)
    requirements = pipeline.step2_requirements(pack, known)
    chosen = pipeline.rank(pack, requirements, budget, known)

    source = build_source(pack)
    verdicts = pipeline.step3_verify(pack, chosen, source)
    lines, verdicts = pipeline.step4_optimize(
        pack, chosen, verdicts, budget, requirements, source)
    reasons = pipeline.step5_reasons(requirements, verdicts, lines)

    spent = sum(ln.price for ln in lines)
    return Recommendation(
        domain=domain, requirements=requirements, claims=verdicts, set=lines,
        budget=budget, spent=spent, reasons=reasons,
        indicators=pipeline.indicators(pack, requirements, lines, verdicts, source),
        screening=pipeline.screen(pack, requirements, known),
        budget_met=not (budget and spent > budget),
        notices=_notices(requirements, budget, spent, verdicts),
        mode="rule",
    )


def _run_strands(pack, query: str, answers: dict | None, domain: str) -> Recommendation:
    """
    에이전트가 순서를 정한다. 산출물은 도구가 남긴 상태에서 조립한다.

    모델의 답 문자열을 응답에 싣지 않는다 — 화면이 읽는 것은 도구가 만든
    구조화 데이터고, 모델이 그걸 다시 쓴 문장은 검증할 수 없다.
    """
    from strands import Agent

    from ..strands_agents import _model
    from . import tools

    tools.bind(pack, query, answers)

    agent = Agent(model=_model(), tools=tools.TOOLS, system_prompt=SYSTEM)
    result = agent(query)

    st = tools.state()
    used = [{"tool": name, "calls": m.call_count, "errors": m.error_count}
            for name, m in sorted(result.metrics.tool_metrics.items())]

    needs = st.get("needs_input") or []
    known = st.get("known", {})
    budget = int(known.get("budget") or 0)
    if needs or "set" not in st:
        return Recommendation(domain=domain, needs_input=needs, budget=budget,
                              tools_used=used, mode="strands")

    requirements = st.get("requirements", [])
    verdicts = st.get("verdicts", [])
    lines = st["set"]
    spent = sum(ln.price for ln in lines)
    return Recommendation(
        domain=domain, requirements=requirements, claims=verdicts, set=lines,
        budget=budget, spent=spent,
        reasons=pipeline.step5_reasons(requirements, verdicts, lines),
        indicators=pipeline.indicators(pack, requirements, lines, verdicts,
                                       build_source(pack)),
        screening=pipeline.screen(pack, requirements, known),
        budget_met=not (budget and spent > budget),
        notices=_notices(requirements, budget, spent, verdicts),
        tools_used=used, mode="strands",
    )
