"""주변기기 결과 가공(payload) — 추천엔진 구현계획 §3.3 E13.

`run_peripherals`가 낸 `PeripheralResult`(pydantic DTO)를 **공개 계약 모양의 dict**로
가공하는 순수 함수 하나(`peripheral_payload`)만 둔다. DB·네트워크·LLM을 전혀 부르지 않고,
읽기 시점에 언제든 다시 계산해도 되는 값만 만든다(계획 §0.3 "① pydantic DTO와 ②
공개 계약 모양의 dict를 만드는 순수 함수").

선택 후보의 계산된 리뷰 상세도 순위 explanation 계약으로 함께 반환한다. DB 연결·재조회는 하지 않는다.

## dict 모양 (계획 §3.3 E13 dict 원문 + 본문 산문에 있는 guide)

```python
{"status": "ready" | "empty" | "skipped",
 "items": [{"kind", "kind_label",
            "product": {"name", "brand", "variant_id", "product_url", "image_url"},
            "price": int, "price_source": "reference_snapshot",
            "price_note": "판매처·관측일 미확인 참고가 — 구매 가능 가격이 아닙니다",
            "requirement": [{"key", "label", "value"}],
            "checks": [{"axis", "label", "state": "ok|unknown|fail", "detail"}],
            "reason": {"status": "ready", "text": <규칙 템플릿>},
            "alternatives": [{"name", "price", "diff", "review", "review_weight", "review_note"}],
            "review": <actual ReviewScoreDetail>, "review_weight": 0,
            "review_note": <리뷰가 순위에 영향을 주지 않았다는 문구>,
            "guide": {"status": "none" | "ready", "text": str}}],
 "empty": [{"kind", "reason"}],
 "totals": {"reference_price": int, "note": "PC 예산과 별도"}}
```

`items[].guide`는 계획 §3.3 E13의 dict 예시 자체에는 없지만, 같은 절 산문이 명시한
"구매 전 확인" 가이드다(아래 "구매 전 확인 가이드" 절) — dict 예시가 누락한 필드라
여기서 채워 넣는다.

## `budget`을 최상위에 안 넣는 이유

`PeripheralResult.budget`(예산 조합 탐색 결과)이 있어도 이 payload의 최상위 키에는
안 싣는다. 계획 §3.3 E13이 적어 둔 dict 모양이 계약이고(코디네이터 지시: "the dict shape
there is the contract"), 거기엔 `budget`이 없다 — 넣으면 계약 밖 필드를 얹는 것이라 나중에
스키마가 반영될 때 되돌리는 수고가 생긴다. `PeripheralResult.budget`은 이 함수를 거치지
않고 `result.budget`으로 여전히 접근할 수 있으니 정보 손실은 없다.

## checks 병합 규칙

품목 하나의 `checks`는 두 출처를 합친다:
1. `pick.checks` — E12 모니터↔PC 교차 검사(ok/unknown/fail 전부, `peripheral_cross` 참고).
2. `result.verification`에서 그 품목의 `VerificationTarget.issues` 중, **축이 1번에 이미
   있지 않은 것만**. `verify_per_item`은 E12가 만든 `extra_issues`를 자기 `issues`에도
   그대로 담으므로(감점 합산을 위해), 축 이름으로 걸러내지 않으면 모니터 교차 검사가
   화면에 두 번 나간다.

judge -> state 매핑은 `verify_per_item`이 실제로 내는 두 가지뿐이다: "확인 필요" -> unknown,
"위반" -> fail(E12 fail 쟁점). ok는 애초에 Issue가 안 생기므로(문제 없으면 쟁점을 안 만든다)
여기서 만들 일이 없다.

## reason은 규칙 템플릿, LLM 호출 없음

수치·부품명·순위는 코드가 이미 가진 값(`PeripheralRequirement`, `PeripheralResult.counts`,
`Candidate.rank`)을 그대로 문장에 옮길 뿐이다. **신뢰도 숫자는 절대 넣지 않는다**(결정
0003)이고, `stage3c_verify._BANNED_KOREAN_VERDICTS`의 판정어도 쓰지 않는다(관측 서술만).

## "구매 전 확인" 가이드

`src.rag.care_guides.SLOT_GUIDE_IDS`에 주변기기 4종을 빈 튜플로 등록해 뒀다(이 파일이 아니라
`care_guides.py`에서) — `search_care_guide(slot=kind)`가 `allowed = ()`를 받아 전 문서
검색으로 새지 않고 빈 결과를 낸다. 이 함수는 그 등록 상태를 안다고 가정하고, **가이드
목록이 비어 있는 종류는 `search_care_guide`를 아예 부르지 않는다** — 임베딩 호출(설령
MOCK_MODE라도 해시 임베딩 계산 비용이 든다)을 걸지 않아야 이 함수가 순수하게 유지되고
테스트가 오프라인으로 돈다. 가이드가 있는 종류가 생기면(문서 작성은 R-12) 그때만
`search_care_guide`를 불러 `{"status": "ready", "text": ...}`를 낸다.
"""
from __future__ import annotations

from typing import Any

from src.dto import Candidate, PeripheralPick, PeripheralRequirement, PeripheralResult
from src.engine import spec_rules
from src.engine.peripheral_catalog import PRICE_NOTE
from src.engine.peripheral_rules import kind_def, load_peripheral_rules
from src.engine.stage3c_verify import axis_label
from src.rag.care_guides import SLOT_GUIDE_IDS, search_care_guide

# 계획 §3.3 E13 원문 문구. PRICE_NOTE("판매처·관측일 미확인 참고가")를 peripheral_catalog에서
# 그대로 가져와 뒤에 고정 문구만 붙인다 — 앞부분 문자열을 이 파일에 다시 적지 않는다.
_PRICE_NOTE_SUFFIX = "구매 가능 가격이 아닙니다"

# "구매 전 확인" 가이드가 없을 때 고정 문구(계획 §3.3 E13).
_GUIDE_NONE_TEXT = "이 품목의 사용 가이드는 아직 없습니다"

# totals.note 고정 문구(계획 §3.3 E13) — 참고가는 PC 총액과 합산하지 않는다는 뜻을 화면에도 남긴다.
_TOTALS_NOTE = "PC 예산과 별도"

# verify_per_item이 실제로 내는 judge 두 가지 -> checks[].state. ok는 Issue 자체가 안 생기므로
# 매핑에 없다(문제 없는 축은 애초에 쟁점이 안 만들어진다).
_JUDGE_TO_STATE = {"확인 필요": "unknown", "위반": "fail"}

# requirement[].label — hard(resolution_class/refresh_min_hz)와 config/peripherals.yaml
# requirements.<kind>.soft가 실제로 쓰는 pref 키(계획 §3.3 E10 표)만 담는다. 여기 없는 키는
# axis_label과 같은 원칙으로 키 이름을 그대로 라벨로 쓴다(모르는 키를 지어내지 않는다).
_REQUIREMENT_KEY_LABEL: dict[str, str] = {
    "resolution_class": "요구 해상도 등급",
    "refresh_min_hz": "요구 최소 주사율(Hz)",
    "panel_raw": "패널",
    "switch_clicky": "클릭형 스위치",
    "switch_magnetic": "마그네틱 스위치",
    "rapid_trigger": "래피드 트리거",
    "polling_hz_max": "폴링레이트(Hz)",
    "connectivity_wireless": "무선 연결",
    "power_source_raw": "전원 방식",
    "channels": "채널 수",
}


def _requirement_label(key: str) -> str:
    return _REQUIREMENT_KEY_LABEL.get(key, key)


def _issue_axis_label(axis: str) -> str:
    """verify_per_item이 직접 만드는 두 축(`<kind>_hard`/`<kind>_data_gap`)은 종류마다
    접두사가 달라 고정 표에 못 담는다 — 접미사로 구분한다. 그 외(E12 축 등)는
    `stage3c_verify.axis_label` 표를 그대로 재사용한다(라벨 표를 두 곳에 만들지 않는다)."""
    if axis.endswith("_hard"):
        return "필수 조건 확인 불가"
    if axis.endswith("_data_gap"):
        return "선호 조건 데이터 결손"
    return axis_label(axis)


def _fmt_pref_value(pref: dict[str, Any]) -> str:
    op, value = pref["op"], pref["value"]
    if op == "min":
        return f"{value} 이상"
    if op == "max":
        return f"{value} 이하"
    if op == "equals":
        if value is True:
            return "예"
        if value is False:
            return "아니오"
        return str(value)
    if op in ("member_of", "contains_any"):
        return "/".join(str(v) for v in value)
    return str(value)


def _requirement_rows(req: PeripheralRequirement) -> list[dict[str, Any]]:
    """PeripheralRequirement(hard + soft preferences) -> [{key, label, value}].

    hard(지금은 monitor만) 먼저, 그다음 soft 선호(중복 제거, YAML 순서 유지). 조건 없이
    기본 해상도를 썼으면(`req.assumed`에 "resolution") 그 사실을 알리는 안내 행을 마지막에
    덧붙인다 — 화면에서 "이 값은 추정입니다"를 구분할 수 있게(계획 §4 원칙 3, "근사는
    근사라고 보고한다").
    """
    rows: list[dict[str, Any]] = []
    if req.hard.get("resolution_class"):
        rows.append({"key": "resolution_class", "label": _requirement_label("resolution_class"),
                     "value": "/".join(req.hard["resolution_class"])})
    if req.hard.get("refresh_min_hz") is not None:
        rows.append({"key": "refresh_min_hz", "label": _requirement_label("refresh_min_hz"),
                     "value": f"{int(req.hard['refresh_min_hz'])}Hz 이상"})

    soft_prefs = spec_rules.dedupe_prefs((req.soft or {}).get("preferences") or [])
    for pref in soft_prefs:
        rows.append({"key": pref["key"], "label": _requirement_label(pref["key"]),
                     "value": _fmt_pref_value(pref)})

    if "resolution" in req.assumed:
        note = req.notes[0] if req.notes else "해상도 조건을 말하지 않아 기본값을 썼습니다"
        rows.append({"key": "resolution_assumed", "label": "해상도 조건(가정)", "value": note})

    return rows


def _reason_text(kind_label: str, req: PeripheralRequirement, cand: Candidate, stats: dict[str, Any]) -> str:
    """규칙 템플릿(LLM 호출 없음, 계획 §3.3 E13 "reason은 규칙 템플릿"). 신뢰도 숫자·판정어를
    넣지 않는다 — 관측 사실(무엇을 목표로 삼았고 몇 개 중 몇 위인가)만 옮긴다.

    "조건 충족 후보 N개 중 k위"는 **탈락 가능한 hard 조건이 있었을 때만** 쓴다(지금은
    monitor뿐). 키보드·마우스·스피커는 hard가 없어(계획 §3.3 E10 — 데이터 결손이 커서
    hard를 안 둠) kept 후보가 전부 "조건을 충족해서" 남은 게 아니라 원래 하드 탈락이
    없었던 것이다 — "조건 충족"이라고 쓰면 실제로 없던 필터링을 있었던 것처럼 보이게
    한다. 그 대신 "후보 N개 중 k위"로만 쓴다. soft 선호가 있으면(랭킹에는 반영됐지만
    탈락 사유는 아니므로) "(선호 조건 반영)"만 짧게 덧붙인다 — 구체적 스펙 이름은
    지어내지 않는다.
    """
    parts: list[str] = []
    if req.hard.get("resolution_class"):
        parts.append("/".join(req.hard["resolution_class"]) + " 해상도")
    if req.hard.get("refresh_min_hz") is not None:
        parts.append(f"{int(req.hard['refresh_min_hz'])}Hz 이상")
    goal = " ".join(parts)

    has_hard = bool(req.hard)
    has_soft = bool((req.soft or {}).get("preferences"))
    kept = int(stats.get("pass", 0)) + int(stats.get("pending", 0))

    if kept:
        base = f"조건 충족 후보 {kept}개 중 {cand.rank}위" if has_hard else f"후보 {kept}개 중 {cand.rank}위"
    else:
        base = f"{kind_label} 후보 중 선정"
    if has_soft:
        base += " (선호 조건 반영)"

    if goal:
        return f"{goal} 목표에 맞는 {kind_label}, {base}"
    return f"{kind_label}, {base}"


def _product_dict(cand: Candidate) -> dict[str, Any]:
    """product_url·image_url 둘 다 Candidate.provenance(peripheral_catalog.
    build_peripheral_provenance)에 있다. image_url은 catalog.product.image_url(DB 로더가
    SELECT, 계획 감사에서 정정 — 이전 버전은 이 컬럼이 없다고 잘못 적었다)과 CSV의
    "이미지 URL" 열 둘 다 채운다. 값이 비어 있으면(구형 데이터 등) provenance에 키 자체가
    없어 여기서도 None — 지어내지 않고 그대로 옮긴다."""
    return {
        "name": cand.name, "brand": cand.brand, "variant_id": cand.variant_id,
        "product_url": cand.provenance.get("product_url"),
        "image_url": cand.provenance.get("image_url"),
    }


def _checks_for_pick(kind: str, pick: PeripheralPick, verification) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = list(pick.checks)
    existing_axes = {c["axis"] for c in checks}
    if verification is None:
        return checks
    for target in verification.targets:
        transcript_kind = (target.transcript[0].get("kind") if target.transcript else None)
        if transcript_kind != kind:
            continue
        for issue in target.issues:
            if issue.axis in existing_axes:
                continue   # E12 쟁점은 pick.checks에 이미 있다(위 모듈 docstring "checks 병합 규칙")
            checks.append({
                "axis": issue.axis, "label": _issue_axis_label(issue.axis),
                "state": _JUDGE_TO_STATE.get(issue.judge, "unknown"), "detail": issue.text,
            })
        break
    return checks


def _alternatives(pick: PeripheralPick) -> list[dict[str, Any]]:
    return [{"name": alt.name, "price": alt.price, "diff": alt.price - pick.candidate.price,
             "review": alt.review_detail.model_dump(mode="json") if alt.review_detail else None,
             "review_weight": 0.0,
             "review_note": "요청 조건과 연결한 참고 적합도이며 주변기기 점수와 순위에는 반영되지 않았습니다."}
            for alt in pick.alternatives]


def _guide_for_kind(kind: str) -> dict[str, str]:
    """가이드 목록이 빈 종류는 search_care_guide를 아예 부르지 않는다(모듈 docstring
    "구매 전 확인 가이드" 참고) — 이 함수가 순수·오프라인으로 남아야 payload도 그렇다."""
    guide_ids = SLOT_GUIDE_IDS.get(kind)
    if not guide_ids:
        return {"status": "none", "text": _GUIDE_NONE_TEXT}
    hits = search_care_guide(kind, k=1, slot=kind)   # 미래에 문서가 생기면(R-12) 여기서만 실제로 호출된다
    if not hits:
        return {"status": "none", "text": _GUIDE_NONE_TEXT}
    return {"status": "ready", "text": hits[0]["text"]}


def _item_dict(kind: str, pick: PeripheralPick, req: PeripheralRequirement,
               stats: dict[str, Any], verification, rules: dict) -> dict[str, Any]:
    cand = pick.candidate
    kdef = kind_def(kind, rules)
    return {
        "kind": kind, "kind_label": kdef["label"],
        "product": _product_dict(cand),
        "price": cand.price, "price_source": cand.price_source,
        "price_note": f"{PRICE_NOTE} — {_PRICE_NOTE_SUFFIX}",
        "requirement": _requirement_rows(req),
        "checks": _checks_for_pick(kind, pick, verification),
        "reason": {"status": "ready", "text": _reason_text(kdef["label"], req, cand, stats)},
        "alternatives": _alternatives(pick),
        "guide": _guide_for_kind(kind),
        "review": cand.review_detail.model_dump(mode="json") if cand.review_detail else None,
        "review_weight": 0.0,
        "review_note": "요청 조건과 연결한 참고 적합도이며 주변기기 점수와 순위에는 반영되지 않았습니다.",
    }


def peripheral_payload(result: PeripheralResult, rules: dict | None = None) -> dict[str, Any]:
    """PeripheralResult -> 공개 계약 모양 dict(계획 §3.3 E13). DB·네트워크·LLM 호출 없음
    (가이드가 있는 종류가 생기기 전까지는 `search_care_guide`도 안 부른다 — 위 참고).

    `requirements`(품목별 `PeripheralRequirement`)가 없으면(=run_peripherals이 넘기지
    않았으면) `requirement`/`reason`을 만들 근거가 없다는 뜻이라 빈 값으로 낸다 — 조용히
    지어내지 않는다.
    """
    if result.status != "ready":
        # skipped/empty 둘 다 품목이 없다. empty는 종류별 이유(result.empty)를 그대로 옮긴다.
        return {
            "status": result.status, "items": [],
            "empty": [dict(e) for e in result.empty],
            "totals": {"reference_price": 0, "note": _TOTALS_NOTE},
        }

    rules = rules or load_peripheral_rules()
    requirements = result.requirements or {}
    items = []
    for pick in result.picks:
        req = requirements.get(pick.kind) or PeripheralRequirement(kind=pick.kind)
        stats = (result.counts or {}).get(pick.kind) or {}
        items.append(_item_dict(pick.kind, pick, req, stats, result.verification, rules))

    return {
        "status": "ready", "items": items,
        "empty": [dict(e) for e in result.empty],
        "totals": {"reference_price": sum(p.candidate.price for p in result.picks), "note": _TOTALS_NOTE},
    }
