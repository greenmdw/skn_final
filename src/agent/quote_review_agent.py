"""견적 점검 되묻기 에이전트 — Strands Agents SDK (CHAT-04).

`POST /pc/reviews/{list_id}/messages` 의 질문에, 저장된 비교 분석 결과(호환 · 가격 · 용도 대비 균형 · 우리 추천 비교)와
대안 조회를 **도구로 읽어** 답한다. 도구는 전부 조회 전용이라 견적·저장된 결과를 바꾸지 않는다.

경계(result_agent 와 같다):
- 사실은 도구가 준 문장만 쓴다. 판정 금지 — "이 견적 사도 돼?", "이 부품이 더 좋아?" 를 에이전트가 정하지 않는다
  (기획서 P7). 확정된 비호환·계산된 차이·확인 못 한 항목을 그대로 전한다.
- 질문에서 규칙(`quote_chat_service.route`)이 고른 사실은 코드가 먼저 조회해 프롬프트에 싣는다 — 모델이 도구를 안 부르고
  "확인할 수 없다"고 답하는 일을 막는다.
- 답변의 숫자는 전부 입력(프롬프트·도구 결과·질문)에 있던 숫자여야 한다. 어긋나면 LLM 문장을 버리고 코드 문장(사실)으로 낸다.
- 대화 이력은 DB(`identity.message`)에서 받는다 — 프로세스 메모리가 아니라 재시작 뒤에도 이어진다.
- `available()` 이 False(MOCK_MODE·키 없음·`QUOTE_REVIEW_AGENT=0`)면 호출자가 규칙 경로로 답한다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from src.agent.conditions_agent import _model
from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY, QUOTE_REVIEW_AGENT

log = logging.getLogger(__name__)

FactFn = Callable[[str, dict], str]          # (도구 이름, 인자) -> 근거 문장
EVIDENCE_LABEL = {"overview": "견적 분석 요약", "compat": "호환 검사", "prices": "가격 비교", "balance": "용도 대비 균형",
                  "compare": "우리 추천과 비교", "alternatives": "대안 조회", "compare_parts": "부품 비교"}


def available() -> bool:
    return (not MOCK_MODE and QUOTE_REVIEW_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


@dataclass
class _Session:
    fact: FactFn
    trace: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)          # 근거로 쓴 분석 블록 이름
    outputs: list[str] = field(default_factory=list)       # 도구가 돌려준 문장 — 수치 가드의 허용 출처
    user_text: str = ""

    def grounded_targets(self, targets: list[str]) -> list[str]:
        """모델이 넘긴 비교 대상 중 사용자 질문에 실제로 적힌 것만 — "9600X"를 물었는데 "7600X"로 옮기는 식의 오독을 막는다.
        코드가 질문에서 찾은 대상은 미리 조회해 두므로(route) 여기서는 모델이 만든 이름만 걸러 낸다."""
        flat = re.sub(r"[\s\-_.]", "", self.user_text.lower())
        keep = []
        for t in targets:
            words = [w for w in re.split(r"[\s\-_.]+", t.lower()) if len(w) >= 3 and any(ch.isdigit() for ch in w)]
            if words and all(w in flat for w in words):
                keep.append(t)
        return keep

    def call(self, name: str, **args) -> str:
        out = self.fact(name, args)
        self.trace.append(f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items() if v)}) → {out[:120]}")
        if EVIDENCE_LABEL[name] not in self.used:
            self.used.append(EVIDENCE_LABEL[name])
        self.outputs.append(out)
        return out


def make_tools(s: _Session) -> list:
    from strands import tool

    @tool
    def overview() -> str:
        """견적 분석 전체 요약(부품, 호환 검사, 가격 비교, 용도 대비 균형, 우리 추천 비교의 핵심)을 돌려준다."""
        return s.call("overview")

    @tool
    def compat(axis: str = "") -> str:
        """호환 검사 결과를 돌려준다. 확정된 비호환, 확인 못 한 항목, 통과한 항목과 각 근거 수치가 들어 있다.

        Args:
            axis: 특정 검사만 볼 때(예: 소켓, 전력, 메모리, GPU 길이, 쿨러 높이). 비우면 전체.
        """
        return s.call("compat", axis=axis)

    @tool
    def prices(part: str = "") -> str:
        """견적에 적힌 가격과 우리 카탈로그 가격의 비교(차이 원·%)를 돌려준다.

        Args:
            part: 부품 슬롯(CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러). 비우면 전체.
        """
        return s.call("prices", part=part)

    @tool
    def balance() -> str:
        """사용자 조건(용도·해상도·예산) 대비 부족하거나 과한 부품과 그 계산 근거를 돌려준다."""
        return s.call("balance")

    @tool
    def compare(part: str = "") -> str:
        """같은 조건으로 만든 우리 추천 구성과 견적을 부품별로 나란히 비교한 결과를 돌려준다.

        Args:
            part: 부품 슬롯. 비우면 전체.
        """
        return s.call("compare", part=part)

    @tool
    def alternatives(slot: str, direction: str = "") -> str:
        """견적 속 부품 하나를 같은 부품군의 다른 제품으로 바꿀 때의 대안 목록을 돌려준다. 견적의 나머지 부품과 새로 생기는
        확정 비호환 여부, 가격 차이, 성능 등급이 들어 있다. 조회만 하며 견적을 바꾸지 않는다.

        Args:
            slot: 부품 슬롯(CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러)
            direction: "cheaper"(더 저렴한) · "better"(더 좋은) · 비우면 가격이 가까운 순
        """
        return s.call("alternatives", slot=slot, direction=direction if direction in ("cheaper", "better") else None)

    @tool
    def compare_parts(slot: str, targets: list[str] | None = None, direction: str = "") -> str:
        """견적 속 부품 하나를 같은 부품군의 다른 제품과 스펙·가격·리뷰로 나란히 비교한다. 견적의 나머지 부품과 새로 생기는 확정
        비호환도 함께 준다. 사용자가 비교하고 싶은 제품 이름을 말했으면 targets 에 넣는다. 조회만 하며 견적을 바꾸지 않는다.

        Args:
            slot: 부품 슬롯(CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러)
            targets: 비교할 제품 이름·모델명 목록(예: ["RTX 4070", "RX 7800 XT"]). 없으면 대안 조회가 고른 후보와 비교.
            direction: targets 가 없을 때 "cheaper"(더 저렴한) · "better"(더 좋은)
        """
        given = [t for t in (targets or []) if t]
        kept = s.grounded_targets(given)
        out = s.call("compare_parts", slot=slot, targets=kept, direction=direction if direction in ("cheaper", "better") else None)
        dropped = [t for t in given if t not in kept]
        if dropped:                        # 질문에 없는 이름은 비교하지 않았다 — 다른 제품 결과를 요청한 것처럼 답하지 않게 밝힌다
            out = f"※ 질문에 적히지 않은 제품({', '.join(dropped)})은 비교 대상에서 뺐습니다.\n" + out
        return out

    return [overview, compat, prices, balance, compare, alternatives, compare_parts]


def system_prompt(review: dict, overview: str, prefetched: str = "") -> str:
    conditions = (review.get("input") or {}).get("conditions") or {}
    given = " · ".join(f"{k} {v}" for k, v in conditions.items()) or "조건 없음"
    return "\n".join([
        "당신은 TrueFit 받은 견적 점검의 도우미입니다. 사용자가 올린 타사 견적을 우리가 분석한 결과(도구)를 근거로 질문에 답합니다.",
        "",
        f"사용자 조건: {given}",
        "분석 요약:",
        overview,
        "",
        "규칙:",
        "1. 답은 도구가 준 문장·수치로만 씁니다. 도구에 없는 수치·사실·성능 평가를 만들지 않습니다.",
        "2. 부품의 좋고 나쁨, 견적을 사도 되는지, 리뷰의 진위를 판정하지 않습니다. 확정된 비호환, 계산된 가격·등급 차이, "
        "'확인 못 함' 항목을 그대로 전하고 판단은 사용자에게 맡깁니다.",
        "3. 호환은 도구가 '확정된 비호환'이라 한 것만 문제로 말합니다. '확인 못 함'은 비호환이 아니라 정보가 없다는 뜻이라고 구분합니다.",
        "4. 같은 부품군의 다른 제품과 스펙·가격·리뷰를 비교해 달라면 compare_parts 를 부릅니다(사용자가 말한 제품 이름은 targets 로). "
        "대안 목록만 물으면 alternatives 를 부르고 목록의 이름·가격·차이를 그대로 전합니다. 견적을 바꾸지는 못하니, 바꾸는 방법은 "
        "안내하지 않고 어떤 대안이 있는지만 말합니다.",
        "5. 답변은 4문장 이내, 한국어 존댓말. '죄송'·'확인할 수 없다'로 시작하지 않고 아는 사실부터 말합니다.",
        "6. 분석 결과에 없는 부품·조건을 물으면 없다고 하고, 견적에 무엇이 들어 있는지 알려 줍니다.",
        *(["", "질문에 대해 미리 조회한 근거(이걸로 답하고, 더 필요하면 도구를 부릅니다):", prefetched] if prefetched else []),
    ])


def _history_messages(history: list[tuple[str, str]]) -> list[dict]:
    msgs = []
    for user, assistant in history:
        msgs.append({"role": "user", "content": [{"text": user}]})
        msgs.append({"role": "assistant", "content": [{"text": assistant}]})
    return msgs


# ── 수치·평가어 가드 ────────────────────────────────────────────────────────
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_EVALUATIVE = ("강력", "뛰어나", "최고", "압도적", "완벽", "훌륭", "우수", "극대화", "추천드", "사셔도", "사도 됩니다", "사지 마")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM_RE.finditer(text or "")}


_SLOT_NAMES = ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러")
_PRICIER_PAT = re.compile(r"비싸|비쌌|웃돌|더\s*비쌈|가격이\s*높")
_CHEAPER_PAT = re.compile(r"저렴|더\s*쌈|가격이\s*낮|보다\s*낮")


def price_claims_are_grounded(reply: str, review: dict) -> bool:
    """"메인보드는 비쌌고" 처럼, 실제로는 비교하지 않은(no_catalog 등) 부품에 비쌈/쌈을 붙이는 오류를 잡는다.

    숫자 가드는 답의 숫자가 입력에 있었는지만 보므로, 진짜 숫자(합계 등)를 실제와 다른 부품에 붙이는 실수는
    통과시킨다(2026-09-27 실측: 가격 비교 3부품 중 1건만 pricier인데 "CPU와 메인보드가 비쌌다"고 답함).

    한 절에 부품이 여러 개 나와도(", CPU와 RAM은 견적이 비싸고"처럼) 절 안의 방향이 하나로만 정해지면
    (비쌈 또는 쌈 중 하나만 나오면) 그 절에 언급된 **모든** 부품에 같은 서술이 적용된 것으로 보고 각각
    대조한다 — "A와 B는 X"는 A·B 둘 다 X 라는 뜻이라 한국어 문법상 안전하다. 실측(2026-09-28)으로 확인한
    사례: "CPU와 RAM은 견적이 비싸고"에서 RAM은 실제로 cheaper인데 검사를 건너뛰어 놓쳤다. 절 안에 비쌈·쌈
    방향어가 둘 다 있으면(어느 부품에 어느 방향이 붙는지 코드가 못 가른다) 그 절은 건너뛴다(과탐 방지)."""
    rows = {r["part"]: r["state"] for r in (review.get("prices") or {}).get("rows") or []}
    if not rows:
        return True
    for clause in re.split(r"[.,]|이며|지만|그러나|그리고", reply):
        present = [s for s in _SLOT_NAMES if s in clause]
        if not present:
            continue
        claims_pricier, claims_cheaper = bool(_PRICIER_PAT.search(clause)), bool(_CHEAPER_PAT.search(clause))
        if claims_pricier == claims_cheaper:      # 둘 다(방향 모호) 또는 둘 다 아님(방향 서술 없음)
            continue
        claimed = "pricier" if claims_pricier else "cheaper"
        for slot in present:
            state = rows.get(slot)
            if state is not None and state != claimed:
                return False
    return True


def reply_is_grounded(reply: str, sources: list[str]) -> tuple[bool, set[str], list[str]]:
    """(통과 여부, 입력에 없던 숫자, 걸린 평가어)."""
    allowed: set[str] = set()
    for src in sources:
        allowed |= _numbers(src)
    outside = _numbers(reply) - allowed
    bad = [w for w in _EVALUATIVE if w in reply]
    return (not outside and not bad), outside, bad


@dataclass
class TurnResult:
    reply: str
    evidence: list[str]
    trace: list[str]


def run_turn(review: dict, history: list[tuple[str, str]], text: str,
             routed: list[tuple[str, dict]], fact: FactFn, user_text: str = "") -> TurnResult:
    """한 턴. `routed` 는 규칙이 고른 조회 — 먼저 실행해 근거로 싣는다."""
    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    session = _Session(fact=fact, user_text=user_text or text)
    pre = "\n\n".join(f"[{EVIDENCE_LABEL[n]}]\n{session.call(n, **a)}" for n, a in routed if n != "overview")
    overview = fact("overview", {})
    prompt = system_prompt(review, overview, pre)
    agent = Agent(
        model=_model(),
        system_prompt=prompt,
        tools=make_tools(session),
        messages=_history_messages(history),
        tool_executor=SequentialToolExecutor(),
        callback_handler=None,
    )
    reply = str(agent(text)).strip()
    ok, outside, bad = reply_is_grounded(reply, [prompt, text, *session.outputs])
    ok = ok and price_claims_are_grounded(reply, review)
    if not ok:
        log.warning("quote review agent reply rejected (numbers %s, words %s) — replaced: %r", sorted(outside), bad, reply[:120])
        facts = pre or overview
        reply = facts
        session.used = session.used or [EVIDENCE_LABEL["overview"]]
    # 도구를 안 부르고 프롬프트의 분석 요약만으로 답한 턴도 근거는 그 요약이다.
    return TurnResult(reply=reply, evidence=list(session.used) or [EVIDENCE_LABEL["overview"]], trace=list(session.trace))
