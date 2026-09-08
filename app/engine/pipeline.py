"""
1~5단계 룰 경로 — 키 없이 끝까지 도는 기준 구현.

`NEGOTIATOR_MODE=rule` 이 협상 쪽 기본값인 것과 같은 배치다. 데모 당일 API 가
흔들려도 같은 화면이 나와야 하고(`docs/해커톤_요건_대조.md` §3), 검사도 키
없이 돌아야 한다. Strands 경로는 `run.py` 에 있고 **같은 함수들을 도구로
부른다** — 두 경로가 다른 답을 낼 자리를 만들지 않는다.

[여기 걸린 두 개의 구속 조건]
목업의 마지막 공개 화면(공정위 사용후기 규정 대응)에 화면 문구가 아니라
**구현 제약**이 섞여 있다. 둘 다 이 파일이 지키고, `tests/test_recommend_engine.py`
가 고정한다.

1. **반증돼도 후보에서 빼지 않는다.** 목업: *"판정은 후보를 제외하지 않는다.
   반증된 항목도 목록에 남고 경고만 붙는다."* 실제로 그래픽카드는 반증됐는데
   대안이 없어 유지 + 경고로 갔다. `optimize()` 는 무엇도 제거하지 않는다 —
   추가하거나 경고를 단다
2. **리뷰는 순위에 직접 반영하지 않는다.** 목업: *"리뷰는 순위에 직접 반영하지
   않는다. 스펙 주장의 진위 판정에만 쓴다."* 그래서 `rank()` 는 판정을 **인자로
   받지 않는다.** 규약이 아니라 시그니처로 막는다 — 받을 수 없으면 못 쓴다
"""

from __future__ import annotations

import re

from .schemas import (
    Claim, ClaimVerdict, Indicators, NeedsInput, Reason, Requirement,
    SetLine, Verdict,
)
from ..reviews import build_source
from .verify import verify_claims


# ── 1단계: 체크리스트 작성 ───────────────────────────────────────────────────
def step1_checklist(pack, query: str, answers: dict | None = None) -> tuple[dict, list[NeedsInput]]:
    """
    입력에서 아는 것을 뽑고, 모르는 것을 되묻는다.

    **무엇을 모르는지 아는 것이 1단계의 일이다.** 여기서 키워드 추출은 룰이다 —
    게임명은 팩의 사전에 있는 것만 인식하고, 없으면 모른다고 한다. Strands
    경로에서는 이 자리를 모델이 대신하지만(기획안 §9: 목적에서 품목을 뽑는 건
    규칙으로 못 쓴다), **팩에 없는 게임을 지어낼 수는 없다** — 2단계의 외부
    사실이 팩에서만 오기 때문이다.
    """
    known: dict = dict(answers or {})
    known.update(pack.extract(query, known))
    return known, pack.followups(known)


def extract_budget(text: str) -> int | None:
    """
    "120만 원" · "1,200,000원" 에서 금액을 뽑는다. **도메인과 무관하다.**

    팩이 쓰라고 여기 둔다 — 돈 읽는 규칙은 PC 든 여행이든 같고, 팩마다 정규식을
    베껴 두면 한쪽만 고쳐진다.
    """
    m = re.search(r"(\d[\d,]*)\s*만\s*원", text)
    if m:
        return int(m.group(1).replace(",", "")) * 10000
    m = re.search(r"(\d[\d,]{5,})\s*원", text)
    return int(m.group(1).replace(",", "")) if m else None


# ── 2단계: 요구사항 확인 ─────────────────────────────────────────────────────
def step2_requirements(pack, known: dict) -> list[Requirement]:
    """외부 사실을 붙여 스펙으로 바꾼다. 사실은 모델이 아니라 팩에서 온다."""
    return pack.external_facts(known)


# ── 3단계 ①②: 하드 제약 + 적합도 ────────────────────────────────────────────
def rank(pack, requirements: list[Requirement], budget: int,
         known: dict | None = None) -> list[dict]:
    """
    조건 미달을 걸러내고 카테고리별로 하나씩 고른다.

    **판정(`ClaimVerdict`)을 인자로 받지 않는다.** 리뷰가 순위에 영향을 줄 수
    없다는 것을 시그니처로 보장하는 자리다 — 목업의 공개 화면이 *"리뷰는 순위에
    직접 반영하지 않는다"* 고 약속했고, 그 약속이 거짓이 되면 공개 화면 전체가
    무너진다. 규약으로 두지 않고 **받을 수 없게** 만든다.

    예산은 여기서 가중치만큼의 배분액으로만 쓴다. 총액을 맞추는 것은 4단계 일이다
    (기획안 §3: 4단계가 최적화). 3단계에서 총액까지 맞춰 버리면 4단계가 반증
    품목을 넣을 여지가 없어진다.
    """
    hard = {r.key: r for r in requirements if r.hard}
    weights = pack.weights()
    catalog = pack.catalog()

    chosen: list[dict] = []
    for category in pack.required_categories(known or {}):
        cands = [p for p in catalog if p["category"] == category and pack.meets(p, hard)]
        if not cands:
            continue
        # 배분액 안에서 가장 비싼 것을 고른다. 배분 안에 아무것도 없으면 그
        # 카테고리의 최저가다 — 하드 제약이 이미 걸러 준 뒤이므로 사는 게 맞다.
        allowance = int(budget * weights.get(category, 0.0)) if budget else 0
        within = [p for p in cands if p["price"] <= allowance]
        chosen.append(max(within, key=lambda p: p["price"]) if within
                      else min(cands, key=lambda p: p["price"]))

    return _repair(pack, chosen, hard)


def _repair(pack, parts: list[dict], hard: dict[str, Requirement],
            pinned: int | None = None) -> list[dict]:
    """
    호환성이 깨지면 같은 카테고리의 다른 후보로 바꾼다.

    바꿀 뿐 **빼지 않는다.** 카테고리 하나가 통째로 빠지면 조립이 안 되는데,
    그건 "조건에 맞는 게 없다"가 아니라 "우리가 못 찾았다"이기 때문이다.

    `pinned` 은 건드리면 안 되는 자리다. 4단계가 메인보드를 올린 뒤 호환성을
    맞출 때, 이 인자가 없으면 수리가 **메인보드를 도로 내려** 방금 한 일을
    되돌린다 — 값이 싼 쪽이 언제나 문제를 줄이기 때문이다.
    """
    parts = list(parts)
    catalog = pack.catalog()
    for _ in range(len(parts) + 1):
        problems = pack.constraints(parts)
        if not problems:
            break
        swapped = False
        for i, part in enumerate(parts):
            if i == pinned:
                continue
            alts = sorted(
                (p for p in catalog
                 if p["category"] == part["category"] and p["code"] != part["code"]
                 and pack.meets(p, hard)),
                key=lambda p: p["price"],
            )
            for alt in alts:
                trial = list(parts)
                trial[i] = alt
                if len(pack.constraints(trial)) < len(problems):
                    parts, swapped = trial, True
                    break
            if swapped:
                break
        if not swapped:
            break
    return parts


# ── 3단계 ③: 스펙 주장 ↔ 리뷰 대조 ──────────────────────────────────────────
def step3_verify(pack, chosen: list[dict], source=None,
                 matcher=None) -> list[ClaimVerdict]:
    """
    고른 품목들이 하는 주장을 리뷰와 대조한다.

    **품목별로 묶어서 넘긴다.** 리뷰는 주장이 아니라 품목에 달려 있어서, 한
    품목에 주장이 둘이면 같은 묶음을 한 번만 읽으면 된다.
    """
    claims_by_part: dict[str, list[Claim]] = {}
    for part in chosen:
        claims = pack.claims_for(part["code"])
        if claims:
            claims_by_part[part["code"]] = claims
    return verify_claims(claims_by_part, source or build_source(pack), matcher)


# ── 4단계: 최적화 — 판정이 되돌아오는 자리 ──────────────────────────────────
def step4_optimize(pack, chosen: list[dict], verdicts: list[ClaimVerdict],
                   budget: int, requirements: list[Requirement] | None = None,
                   source=None) -> tuple[list[SetLine], list[ClaimVerdict]]:
    """
    세트를 만든다. **반증 판정이 구성에 관여한다.**

    목업이 이 자리를 *"검증이 설명용 장식이 아니라 구성에 관여한다는 증거"* 라고
    적었다 — CPU 기본 쿨러 주장이 반증되면서 쿨러 34,000원이 세트에 들어간다.
    3단계가 4단계로 되돌아오는 유일한 경로이고, 여기가 없으면 3단계는 화면
    장식이다.

    **무엇도 제거하지 않는다.** 반증된 품목은 경고를 달고 남는다.

    구성이 바뀌면 **판정을 다시 낸다.** 예산을 맞추다 품목이 바뀌었는데 판정이
    옛 품목의 것이면, 화면이 세트에 없는 물건의 주장을 보여주게 된다. 그래서
    판정도 함께 돌려준다 — 호출자는 이쪽을 써야 한다.
    """
    hard = {r.key: r for r in (requirements or []) if r.hard}
    weights = pack.weights()
    parts = list(chosen)
    added: dict[str, str] = {}
    warnings: dict[str, str] = {}

    for _ in range(3):
        _apply_remedies(pack, parts, verdicts, hard, added, warnings)
        fitted = _fit(pack, parts, budget, hard, weights)
        if {p["code"] for p in fitted} == {p["code"] for p in parts}:
            parts = fitted
            break
        parts = fitted
        verdicts = step3_verify(pack, parts, source)

    lines = [SetLine(category=p["category"], code=p["code"], name=p["name"],
                     price=p["price"], added_by_claim=added.get(p["code"]),
                     warning=warnings.get(p["code"], ""))
             for p in parts]
    return lines, verdicts


def _apply_remedies(pack, parts: list[dict], verdicts: list[ClaimVerdict],
                    hard: dict[str, Requirement], added: dict[str, str],
                    warnings: dict[str, str]) -> None:
    """
    반증 판정을 구성에 반영한다. `parts` 를 제자리에서 고친다.

    경고는 **주장의 주인**에게 붙고, 추가된 품목에는 `added_by_claim` 이 붙는다.
    목업의 두 장면이 각각 이 두 갈래다 — 쿨러는 편성되고(추가), 그래픽카드는
    대안이 없어 유지되며 경고만 받는다.
    """
    catalog = pack.catalog()
    for cv in verdicts:
        if cv.verdict is not Verdict.REFUTED or cv.claim.remedy is None:
            continue
        remedy = cv.claim.remedy

        present = {p["code"] for p in parts}
        for code in _codes_of(pack, cv.claim) & present:
            warnings[code] = remedy.warning

        add = remedy.add_category
        if not add or add in {p["category"] for p in parts}:
            continue
        cands = [p for p in catalog if p["category"] == add and pack.meets(p, hard)]
        if not cands:
            continue
        part = min(cands, key=lambda p: p["price"])
        parts.append(part)
        added[part["code"]] = cv.claim.claim_id


def _fit(pack, parts: list[dict], budget: int, hard: dict[str, Requirement],
         weights: dict[str, float]) -> list[dict]:
    """
    예산에 맞춘다. 초과면 내리고, 남으면 올린다. **무엇도 빼지 않는다.**

    올리는 쪽이 있는 이유는 배분액 그리디가 예산을 다 안 쓰기 때문이다. 남은
    돈은 가중치가 높은 카테고리부터 쓴다 — 기획안 §3의 4단계가 *"예산을 항목별
    가중치로 배분하고 정렬"* 이라고 적은 그대로다.

    한 칸을 올리면 호환성이 깨질 수 있고(메인보드를 올리면 메모리 규격이 바뀐다)
    그때는 `_repair` 가 따라 올린다. 그래서 교체 비용이 한 품목의 차액보다 클 수
    있고, 예산 검사는 **수리까지 끝난 총액**으로 한다.
    """
    if not budget:
        return parts
    parts = list(parts)
    catalog = pack.catalog()

    def cost(ps: list[dict]) -> int:
        return sum(p["price"] for p in ps)

    def settle(i: int, alt: dict) -> list[dict] | None:
        trial = list(parts)
        trial[i] = alt
        trial = _repair(pack, trial, hard, pinned=i)
        return None if pack.constraints(trial) else trial

    # ① 초과 — 총액이 예산 안에 들어올 때까지 내린다
    for _ in range(len(parts) * 2):
        if cost(parts) <= budget:
            break
        best = None
        for i, part in enumerate(parts):
            for alt in sorted((p for p in catalog
                               if p["category"] == part["category"]
                               and p["price"] < part["price"] and pack.meets(p, hard)),
                              key=lambda p: -p["price"]):
                trial = settle(i, alt)
                if trial is None:
                    continue
                if best is None or cost(trial) < cost(best):
                    best = trial
                break
        if best is None:
            break
        parts = best

    # ② 여유 — 가중치가 높은 카테고리부터 올린다
    for _ in range(len(parts) * 2):
        best = None
        best_key = None
        for i, part in enumerate(parts):
            for alt in sorted((p for p in catalog
                               if p["category"] == part["category"]
                               and p["price"] > part["price"] and pack.meets(p, hard)),
                              key=lambda p: p["price"]):
                trial = settle(i, alt)
                if trial is None or cost(trial) > budget:
                    continue
                key = (weights.get(part["category"], 0.0), cost(trial))
                if best_key is None or key > best_key:
                    best, best_key = trial, key
        if best is None:
            break
        parts = best

    return parts


def _codes_of(pack, claim: Claim) -> set[str]:
    """이 주장이 어느 품목의 것인지. 경고를 붙일 줄을 찾는 데만 쓴다."""
    return {p["code"] for p in pack.catalog()
            if any(c.claim_id == claim.claim_id for c in pack.claims_for(p["code"]))}


# ── 5단계: 설명 생성 ────────────────────────────────────────────────────────
def step5_reasons(requirements: list[Requirement], verdicts: list[ClaimVerdict],
                  lines: list[SetLine]) -> list[Reason]:
    """
    근거 문장. **각 문장이 판정과 일대일로 연결된다**(`claim_id`).

    목업: *"근거 문장의 각 주장은 단계 3의 판정과 일대일로 연결된다. 설명이
    스스로 지어낸 문장이 아니라는 것이 이 화면의 요지다."* 여기는 템플릿이고,
    LLM 설명 제너레이션은 `report.py` 의 방식(사실 dict 만 넘기고 어긋나면
    템플릿으로 되돌린다)을 그대로 옮겨 붙일 자리다.
    """
    out: list[Reason] = []

    for r in requirements:
        if r.hard and r.as_of:
            out.append(Reason(text=(
                f"{r.origin}에 따라 {r.key.upper()} {r.value} 를 하드 제약으로 걸었습니다"
                f" (기준 {r.as_of})."
            )))

    for cv in verdicts:
        c, ev = cv.claim, cv.evidence
        if cv.verdict is Verdict.REFUTED:
            added = next((ln for ln in lines if ln.added_by_claim == c.claim_id), None)
            tail = (f" {added.name} {added.price:,}원을 세트에 넣었습니다."
                    if added else " 대안이 없어 유지하고 경고만 답니다.")
            out.append(Reason(claim_id=c.claim_id, text=(
                f"{c.subject}의 \"{c.text}\" 주장은 반증됐습니다 ({ev.note})." + tail
            )))
        elif cv.verdict is Verdict.NO_EVIDENCE:
            out.append(Reason(claim_id=c.claim_id, text=(
                f"{c.subject}의 \"{c.text}\" 는 {ev.note} 판정하지 않았습니다. "
                f"확인했다고 말하지 않습니다."
            )))
        elif cv.verdict is Verdict.PARTLY:
            out.append(Reason(claim_id=c.claim_id, text=(
                f"{c.subject}의 \"{c.text}\" 는 부분적으로만 확인됩니다 ({ev.note})."
            )))
    return out


# ── §7 세 지표 ──────────────────────────────────────────────────────────────
def indicators(pack, requirements: list[Requirement], lines: list[SetLine],
               verdicts: list[ClaimVerdict], source) -> Indicators:
    """
    합치지 않는다. 필드가 없으면 화면도 못 합친다 — 그게 §7의 요구다.
    """
    parts = [_part(pack, ln.code) for ln in lines]
    problems = pack.constraints(parts)

    # 분모는 요구사항 전체 + 호환성 1건이다. 호환성을 문제 건수로 세지 않는
    # 이유는 문제 하나가 여러 문장으로 보고될 수 있어서다 — 분모가 흔들린다.
    #
    # **판정하지 못한 조건은 충족으로 세지 않는다.** 목업의 "미충족 1건 — 144Hz
    # 기준 평균 프레임은 실측 표본이 부족해 판정하지 않았다"가 그 자리이고,
    # 3단계의 NO_EVIDENCE 와 같은 원칙이다 — 모르는 것을 모른다고 말한다.
    unjudged = [f"{r.key}: {r.unjudged_reason}" for r in requirements if not r.judged]
    unmet = problems + unjudged
    total = len(requirements) + 1
    met = total - len(unjudged) - (1 if problems else 0)

    counts: dict[str, int] = {}
    for cv in verdicts:
        counts[cv.verdict.value] = counts.get(cv.verdict.value, 0) + 1

    # 대조에 쓴 리뷰 수는 주장별 표본의 **합이 아니다.** 한 품목에 주장이 둘이면
    # 같은 리뷰 묶음을 두 주장이 나눠 쓰므로 합계는 그만큼 겹쳐 센다. 분포는
    # 리뷰 단위라 겹치지 않으니 거기서 읽는다 — 임계값 아래 구간이 곧 대조에
    # 쓴 것이다.
    buckets = source.risk_distribution()
    threshold = getattr(source, "threshold", 0.20) * 100
    compared = sum(n for label, n in buckets.items()
                   if float(label.split("-")[1].rstrip("%")) <= threshold)

    return Indicators(
        conditions_met=met,
        conditions_total=total,
        conditions_unmet=unmet,
        verdicts=counts,
        samples_compared=compared,
        review_risk_buckets=buckets,
    )


def _part(pack, code: str) -> dict:
    return next((p for p in pack.catalog() if p["code"] == code), {"code": code})
