"""[5] 설명 생성.

(a) 속성 기여도 — 계산(LLM 아님). [3-B] breakdown 을 세트 단위로 집계 → 축별 비율(가격·성능·밸런스·리뷰·호환여유, 합 100%).
(b) 문장 — LLM structured output 1회. 수치·부품명·통과여부는 코드가 확정, LLM 은 서술만.
    실패 시 규칙 템플릿 fallback.
(c) 리뷰 관측 — [3-B] 가 후보에 남긴 REVIEW_OBS flags 를 슬롯별 한 줄(review_line_by_slot)과
    근거 문장(items[].evidence)으로. 점수가 아니라 관측이고 개별 리뷰의 진위가 아니다.
    대조군 중앙값을 넘은 것은 "주의" 로도 올린다 — 검토자가 반박할 수 있게 확인 경로를 같이 준다.
"""
from __future__ import annotations

from src.clients.llm_client import call_llm
from src.dto import (BuildResult, Explanation, ExplanationDraft, ExplanationItem, RankResult,
                     VerificationResult)
from src.engine import LogFn
from src.engine.lang import fmt_money
from src.engine.prompts import explain_system
from src.repo.review_repo import (OBS_LABEL, default_risk_store, default_suspect_counts,
                                 is_obs_flag, parse_obs_flag, risk_store_note)

_AXIS_MAP = {"가격": "가격", "성능": "성능", "밸런스": "호환성", "호환여유": "호환성"}

# 앞 넷: 지시문 문구가 결과에 들어오면 모델이 프롬프트를 베낀 것이다 — 실제로 한 번 그랬다.
# 마지막 여섯: 평가·마케팅 표현 — 규칙 7 위반(실호출에서 "강력한 성능"처럼 새나온 적 있다).
# 뒤 셋: summary 실호출에서 "성능을 극대화", "원활하게 구동", "안정성이 확인된" 이 나왔다 — 입력에 없는 성능 주장.
_BANNED_IN_DRAFT = ("score", "점수", "1~2문장", "문장 한두 개", "슬롯마다", "지시문",
                    "강력", "뛰어나", "최고", "압도적", "완벽", "훌륭", "극대화", "원활", "안정성")


def _ranked_flags(rank: RankResult | None, slot: str, product_key: str) -> list[str]:
    if rank is None:
        return []
    for c in rank.slots.get(slot, {}).get("ranked", []):
        if c.get("product_key") == product_key:
            return [f for f in c.get("flags", []) if is_obs_flag(f)]
    return []


def _review_line(product_key: str, flags: list[str]) -> tuple[str, list[dict], str | None]:
    """(슬롯 한 줄, 근거 목록, 주의 문장 또는 None). flags 가 없으면 관측 없음."""
    if not flags:
        # 왜 없는지를 원인별로 말한다 — 산출물 미탑재를 "문턱 미만" 으로 보이게 하면
        # 파일을 안 받은 사람이 그 사실을 모른다.
        return f"리뷰 관측 없음 ({risk_store_note()})", [], None
    store = default_risk_store()
    facts = store.get(product_key) if store else None
    n = int(facts["n"]) if facts else 0
    over = [p for p in map(parse_obs_flag, flags) if p is not None]
    evidence = []
    if store and facts:
        ref = store.resolve(product_key)
        evidence = [{"kind": "review_observation", "text": t, "verify_url": f"https://www.amazon.com/dp/{ref}"}
                    for t in store.observations(product_key)]
        # 규칙 기반 의심 건수 — kind 를 달리 둬서 관측 사실과 구별한다(정밀도를 못 재는 값이다)
        sus = default_suspect_counts()
        line = sus.sentence(product_key) if sus else None
        if line:
            evidence.append({"kind": "review_suspect_rule", "text": line, "verify_url": None})
    if not over:
        return f"리뷰 {n}건 관측 — 대조군 중앙값 대비 특이 없음", evidence, None
    parts = [f"{OBS_LABEL.get(k, k)} {100 * v:.1f}% (부류 중앙값 {100 * m:.1f}%)" for k, v, m in over]
    line = f"리뷰 {n}건 관측 — " + " · ".join(parts) + " — 검토 권장"
    names = ", ".join(OBS_LABEL.get(k, k) for k, _, _ in over)
    caveat = f"리뷰 관측({names})은 상품 단위 신호이며 개별 리뷰의 진위가 아닙니다"
    return line, evidence, caveat


def explain_manual(service, request):
    """Actual source-only explanation; does not invent a procedure or safety score."""
    from dataclasses import replace
    return service.answer(replace(request, purpose="recommendation"))


def _contribution(build: BuildResult, rank: RankResult | None) -> dict[str, int]:
    """고른 구성이 [3-B] 점수를 어느 축에서 얻었는지(%, 합 100).

    후보 점수 = Σ 축 가중치 × 축 값(breakdown). 고른 부품마다 그 항을 축별로 더해 전체 대비 비율로 낸다.
    (감점 — 검토 보류·검사 스펙 공백 — 은 축이 아니라서 여기엔 안 들어간다.)
    rank 가 없으면(옛 호출) 만들 근거가 없으므로 빈 dict — 가짜 값을 대신 채우지 않는다."""
    if rank is None or not rank.weights_used:
        return {}
    acc: dict[str, float] = {}
    for it in build.items:
        info = rank.slots.get(it.slot) or {}
        # 넓힌 탐색([4])이 top-N 밖에서 고른 부품은 pool 에만 있다.
        cand = next((c for key in ("ranked", "pool") for c in info.get(key, []) if c.get("product_key") == it.product_key), None)
        if cand is None:
            continue
        for axis, value in (cand.get("breakdown") or {}).items():
            acc[axis] = acc.get(axis, 0.0) + max(0.0, rank.weights_used.get(axis, 0.0) * value)
    total = sum(acc.values())
    if total <= 0:
        return {}
    # 반올림해도 합이 100 이 되게 — 소수부가 큰 축부터 1씩 나눠 받는다(최대잔여법).
    exact = {axis: v / total * 100 for axis, v in acc.items()}
    out = {axis: int(v) for axis, v in exact.items()}
    for axis in sorted(exact, key=lambda a: exact[a] - out[a], reverse=True)[:100 - sum(out.values())]:
        out[axis] += 1
    return out


def _top_axes(rank: RankResult | None, slot: str, product_key: str) -> str:
    """그 후보에서 기여가 큰 축 둘 — 이유 문장의 방향 힌트 (기획서 §11-3)."""
    if rank is None:
        return ""
    for c in rank.slots.get(slot, {}).get("ranked", []):
        if c.get("product_key") == product_key:
            bd = c.get("breakdown") or {}
            top = sorted(bd.items(), key=lambda kv: kv[1], reverse=True)[:2]
            return ", ".join(k for k, _ in top)
    return ""


_MODE_LABEL = {"build": "새로 조립", "upgrade": "업그레이드"}


def _condition_text(key: str, value) -> str:
    """리스트·딕셔너리를 파이썬 repr 로 흘리지 않고 읽히게 — LLM 이 "['GPU']" 를 그대로 받던 것을 고친다."""
    if key == "mode":
        return _MODE_LABEL.get(value, str(value))
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _conditions_lines(conditions: dict | None) -> list[str]:
    """[5] 입력에 싣는 사용자 조건. 엔진이 읽지 않는 extra 는 그렇게 표시해 LLM 이 반영됐다고 쓰지 못하게 한다."""
    if not conditions:
        return []
    labels = {"purpose": "용도", "priority": "우선순위", "games": "게임", "resolution": "해상도",
              "noise_sensitive": "소음 민감", "brand_pref": "브랜드 선호", "assembly": "조립", "mode": "구성 방식",
              "upgrade_parts": "업그레이드 부품", "current_specs": "현재 사양"}
    parts = [f"{label} {_condition_text(k, conditions[k])}" for k, label in labels.items()
             if conditions.get(k) not in (None, [], "", {})]
    # extra(자유 조건)는 엔진이 읽지 않는다. LLM 에 보여 주면 "반영됐다"고 쓰는 일이 있어(실호출에서
    # "케이스는 흰색으로 선택할 수 있으며") 입력에서 빼고, 안내 문장은 코드가 summary 뒤에 붙인다(_extra_note).
    return ["사용자 조건: " + (" · ".join(parts) if parts else "(없음)")]


def _extra_note(conditions: dict | None) -> str:
    extra = (conditions or {}).get("extra") or []
    if not extra:
        return ""
    quoted = ", ".join(f"'{e}'" for e in extra)
    return f" 추가 조건 {quoted}은(는) 자동 구성에 반영되지 않았습니다 — 후보 교체나 아래 대화창에서 직접 확인해 주세요."


def _llm_draft(build: BuildResult, verification: VerificationResult,
               rank: RankResult | None, log: LogFn, *,
               conditions: dict | None = None) -> ExplanationDraft | None:
    """문장 초안 1회 생성. 검사를 통과한 것만 돌려주고 아니면 None → 규칙 템플릿 (§11-6).

    수치·부품명·통과여부는 아래 입력으로 확정해 준다. LLM 이 슬롯을 바꾸거나 다른 슬롯의
    부품을 끌어오거나 점수를 만들어내면 버린다 — 그 경우 호출자가 기존 규칙 문장을 쓴다.
    """
    tgt = verification.targets[0] if verification.targets else None
    # 세트 신뢰도·회색축은 입력에서 뺐다 — 규칙 스캐폴드 값(100−감점, RAG 미연결)이라 사용자에게 보일 단계가
    # 아니고, 입력에 있으면 규칙에서 빼도 모델이 인용한다(docs/decisions/0003). 값은 verification.confidence 에 남는다.
    lines = _conditions_lines(conditions) + [
        f"예산 상한: {fmt_money(build.budget.get('max', 0))}",
        f"사용 금액: {fmt_money(build.totals.get('price', 0))}",
        "구성:",
    ]
    for it in build.items:
        axes = _top_axes(rank, it.slot, it.product_key)
        lines.append(f"- {it.slot} | {it.name} | {fmt_money(it.price)} | {it.rank_from_3b}순위"
                     + (f" | 기여가 큰 축: {axes}" if axes else ""))
    if tgt and tgt.issues:
        lines.append("검증 쟁점:")
        lines += [f"- {i.axis}: {i.text or i.tool_result}" for i in tgt.issues]

    want = {it.slot for it in build.items}
    names = {it.slot: it.name for it in build.items}
    schema = ExplanationDraft.model_json_schema()
    for _attempt in range(2):
        try:
            draft = ExplanationDraft.model_validate(
                call_llm("\n".join(lines), system=explain_system(), output_schema=schema))
        except Exception as exc:
            log(f"      [5] 문장 생성 실패 ({type(exc).__name__}) → 규칙 템플릿")
            return None
        if {i.slot for i in draft.items} != want:
            continue
        # headline·summary 에 금지어가 있으면 초안 전체를 버린다(재시도). items 는 슬롯별로 걸러 —
        # reason 한두 개의 금지어 때문에 8슬롯 전부 템플릿으로 떨어지지 않게.
        if any(w.casefold() in (draft.headline + " " + draft.summary).casefold() for w in _BANNED_IN_DRAFT):
            continue
        bad_slots = [i.slot for i in draft.items
                     if any(w in i.reason.lower() for w in _BANNED_IN_DRAFT)
                     or any(other and other in i.reason for slot, other in names.items() if slot != i.slot)]
        if bad_slots:
            log(f"      [5] 슬롯 {bad_slots} reason 은 금지어/타 슬롯 부품 → 그 슬롯만 규칙 템플릿")
            draft.items = [i for i in draft.items if i.slot not in bad_slots]
        if len({i.reason for i in draft.items}) < len(draft.items):
            # 지금 슬롯마다 후보를 1개만 저장해서 전부 "1순위" — 규칙 5의 첫 템플릿이
            # 모든 품목에 똑같이 걸리기 쉽다. 서로 다른 품목인데 문장이 겹치면(토씨만
            # 다른 것도 포함해 완전 동일한 경우만 여기서 걸러진다) 프롬프트 지시(규칙 5
            # 구분 문구)를 안 지킨 것이므로 규칙 템플릿(품목별로 원래 다른 값)으로 내린다.
            continue
        return draft
    log("      [5] 검사 불통과 → 규칙 템플릿")
    return None


def _fallback_reason(item) -> str:
    return f"{item.name} — 조건 충족, {item.rank_from_3b}순위, {fmt_money(item.price)}"


def _fallback_headline(build: BuildResult) -> str:
    budget = build.budget.get("max", 0)
    used = build.totals.get("price", 0)
    return f"예산 {fmt_money(budget)} 중 {fmt_money(used)} 사용."


def _fallback_summary(build: BuildResult) -> str:
    budget = build.budget.get("max", 0)
    used = build.totals.get("price", 0)
    biggest = max(build.items, key=lambda i: i.price, default=None)
    return (
        f"{len(build.items)}개 부품, 예산 {fmt_money(budget)} 중 {fmt_money(used)}을 썼습니다."
        + (f" 비중이 가장 큰 슬롯은 {biggest.slot}({fmt_money(biggest.price)})입니다." if biggest else "")
        + " 부품별 선택 이유는 각 항목에서 볼 수 있습니다."
    )


def run(build: BuildResult, verification: VerificationResult, log: LogFn,
        rank: RankResult | None = None, *, conditions: dict | None = None,
        extra_caveats: list[str] | None = None, scope_note: str = "") -> Explanation:
    log("[5] 설명 생성 ...")
    contrib = _contribution(build, rank)
    tgt = verification.targets[0] if verification.targets else None
    gray = tgt.gray_axes if tgt else []

    # 리뷰 관측(review_line_by_slot·evidence)은 규칙이 만든 것을 그대로 둔다 — LLM 은 건드리지 않는다.
    draft = _llm_draft(build, verification, rank, log, conditions=conditions)
    reason_by_slot = {i.slot: i.reason for i in draft.items} if draft else {}

    items, review_lines, review_caveats = [], {}, []
    for it in build.items:
        line, evidence, caveat = _review_line(it.product_key, _ranked_flags(rank, it.slot, it.product_key))
        review_lines[it.slot] = line
        if caveat:
            review_caveats.append(f"{it.slot} {caveat}")
        items.append(ExplanationItem(
            slot=it.slot,
            reason=(reason_by_slot.get(it.slot) or _fallback_reason(it)),
            basis=[f"rank{it.rank_from_3b}"],
            evidence=evidence,
        ))
    # caveats 는 규칙이 소유한다 — 코드가 정확히 알고 있어서, LLM 이 같은 내용을 다른 표현으로 또 쓰면
    # 화면에 중복으로 나간다. 회색축("근거는 확인되지 않았습니다")은 개발 상태 설명이라 사용자 문장에서 뺐다
    # (docs/decisions/0003) — 아래 로그에만 남긴다.
    caveats = [*(extra_caveats or []), *review_caveats]     # 업그레이드 미확인 안내는 코드가 만든 문장(LLM 아님)
    headline = (draft.headline if draft and draft.headline
                else _fallback_headline(build))
    summary = (draft.summary if draft and draft.summary else _fallback_summary(build)) + _extra_note(conditions) + scope_note
    if gray:
        log(f"      근거 미확인 축(화면에는 안 나감): {', '.join(gray)}")
    log("      기여도: " + (" / ".join(f"{axis} {pct}%" for axis, pct in contrib.items()) or "(순위 정보 없음)"))
    log(f"      문장: {'LLM' if draft else '규칙 템플릿'}")
    log(f"      headline: {headline}")
    n_obs = sum(1 for l in review_lines.values() if not l.startswith("리뷰 관측 없음"))
    log(f"      리뷰 관측: {n_obs}/{len(review_lines)} 슬롯" + (f", 검토 권장 {len(review_caveats)}" if review_caveats else ""))

    return Explanation(
        list_id=build.list_id,
        headline=headline,
        summary=summary,
        contribution=contrib,
        items=items,
        caveats=caveats,
        review_line_by_slot=review_lines,
    )
