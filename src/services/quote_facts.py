"""견적 점검 결과(저장된 `quote_review`)를 근거 문장으로 옮긴다 — 되묻기 채팅(CHAT-04)의 유일한 사실 출처.

에이전트 도구와 규칙 경로가 같은 문장을 쓴다. 저장된 값만 옮기고 새 수치·판정을 만들지 않는다: 호환은 "확정된 비호환"과
"확인 못 함"을 구분해 적고, 가격·균형·추천 비교는 계산된 숫자와 그 근거 문장(detail)을 그대로 실는다.
저장된 블록이 없으면(이 기능 이전 결과, 조건 없음, 가격 없음) 그 이유를 그대로 전한다.
"""
from __future__ import annotations

_STATE_TEXT = {"ok": "통과", "fail": "확정된 비호환", "unknown": "확인 못 함", "skipped": "해당 부품이 없어 보지 않음"}
_BALANCE_TEXT = {"short": "부족", "excess": "과함", "ok": "충족", "unknown": "확인 못 함"}
_PRICE_TEXT = {"cheaper": "견적이 더 쌈", "similar": "비슷함", "pricier": "견적이 더 비쌈",
               "no_quote_price": "견적에 가격 없음", "no_catalog": "비교 못 함"}


def _won(n: int | None) -> str:
    return "-" if n is None else f"{n:,}원"


def overview(review: dict) -> str:
    lines: list[str] = []
    parts = review.get("parts") or []
    if parts:
        lines.append("견적 부품: " + " / ".join(f"{p['part']} {p['matched']}" + ("" if p["state"] == "ok" else "(카탈로그 확정 아님)")
                                            for p in parts))
    compat = review.get("compat") or {}
    summary = compat.get("summary") or {}
    incompatible = compat.get("incompatible") or []
    labels = {c["axis"]: c["label"] for c in compat.get("checks") or []}
    lines.append("호환 검사: " + (f"확정된 비호환 {len(incompatible)}건({', '.join(labels.get(a, a) for a in incompatible)})"
                                if incompatible else "확정된 비호환 없음")
                 + f" · 통과 {summary.get('ok', 0)} · 확인 못 함 {summary.get('unknown', 0)}")
    prices = review.get("prices") or {}
    if prices.get("available"):
        s = prices["summary"]
        lines.append(f"가격 비교: {s['compared']}개 부품 비교(견적이 비쌈 {s['pricier']} · 비슷함 {s['similar']} · 쌈 {s['cheaper']})"
                     f", 비교한 부품 합계 견적 {_won(s['quoted_total'])} · 카탈로그 {_won(s['catalog_total'])}")
    else:
        lines.append("가격 비교: " + (prices.get("reason") or "결과 없음"))
    balance = review.get("balance") or {}
    if balance.get("available"):
        b = balance["summary"]
        lines.append(f"용도 대비 균형({balance['requirement']['label']} 기준): 부족 {b['short']} · 과함 {b['excess']} · 충족 {b['ok']} · 확인 못 함 {b['unknown']}")
    else:
        lines.append("용도 대비 균형: " + (balance.get("reason") or "결과 없음"))
    compare = review.get("compare") or {}
    if compare.get("available"):
        s = compare["summary"]
        lines.append(f"우리 추천과 비교: 우리 추천 합계 {_won(s['our_total'])}(예산 {_won(s['budget'])}), 같은 제품 {s['same_product']}개")
    else:
        lines.append("우리 추천과 비교: " + (compare.get("reason") or "결과 없음"))
    return "\n".join(lines)


def compat(review: dict, axis: str = "") -> str:
    block = review.get("compat") or {}
    rows = block.get("checks") or []
    if axis:
        key = axis.strip().lower()
        rows = [c for c in rows if key in (c["axis"].lower(), c["label"].lower()) or key in c["label"].lower()]
        if not rows:
            return f"'{axis}' 검사가 없습니다. 검사: {', '.join(c['label'] for c in block.get('checks') or [])}"
    order = {"fail": 0, "unknown": 1, "ok": 2, "skipped": 3}
    return "\n".join(f"- {c['label']}: {_STATE_TEXT[c['state']]} — {c['detail']}" for c in sorted(rows, key=lambda c: order[c["state"]]))


def prices(review: dict, part: str = "") -> str:
    block = review.get("prices") or {}
    if not block.get("available"):
        return block.get("reason") or "가격 비교 결과가 없습니다."
    rows = [r for r in block["rows"] if not part or r["part"] == part]
    if not rows:
        return f"'{part}' 부품의 가격 정보가 견적에 없습니다."
    lines = [f"- {r['part']}: {_PRICE_TEXT[r['state']]} — {r['detail']}" for r in rows]
    if not part:
        s = block["summary"]
        lines.append(f"비교한 {s['compared']}개 합계: 견적 {_won(s['quoted_total'])} · 카탈로그 {_won(s['catalog_total'])} "
                     f"(차이 {s['diff']:+,}원" + (f", {s['diff_pct']:+.1f}%" if s.get('diff_pct') is not None else "") + ")")
    return "\n".join(lines)


def balance(review: dict) -> str:
    block = review.get("balance") or {}
    if not block.get("available"):
        return block.get("reason") or "용도 대비 균형 결과가 없습니다."
    lines = [f"기준: {block['requirement']['label']} (GPU 등급 ≥ {block['requirement']['gpu_tier_min']:g}, CPU 등급 ≥ "
             f"{block['requirement']['cpu_tier_min']:g}, RAM ≥ {block['requirement']['ram_gb_min']}GB)"]
    lines += [f"- {r['part']} {r['aspect']}: {_BALANCE_TEXT[r['state']]} — {r['detail']}" for r in block["rows"]]
    lines += [f"참고: {n}" for n in block.get("notes") or []]
    return "\n".join(lines)


def compare(review: dict, part: str = "") -> str:
    block = review.get("compare") or {}
    if not block.get("available"):
        return block.get("reason") or "우리 추천과 비교한 결과가 없습니다."
    rows = [r for r in block["rows"] if not part or r["part"] == part]
    if not rows:
        return f"'{part}' 부품의 비교 결과가 없습니다."
    lines = [f"- {r['part']}: {r['detail']}" for r in rows]
    if not part:
        s = block["summary"]
        lines.append(f"우리 추천 합계 {_won(s['our_total'])} (예산 {_won(s['budget'])}" + (", 초과" if s["over_budget"] else "") + ")")
        lines += [f"참고: {n}" for n in block.get("notes") or []]
    return "\n".join(lines)


def alternatives(result: dict) -> str:
    """`quote_alternatives.alternatives` 결과를 문장으로."""
    if result.get("error"):
        return result["error"]
    base = result["baseline"]
    head = f"{result['slot']} 현재: {base['name']}" + (f" {_won(base['price'])}" if base.get("price") is not None else "")
    if not result["candidates"]:
        return head + " · 조건에 맞는 다른 후보가 카탈로그에 없습니다."
    lines = [head]
    for i, c in enumerate(result["candidates"], 1):
        fail = f" · ⚠ 견적의 다른 부품과 확정된 비호환: {', '.join(c['incompatible'])}" if c["incompatible"] else ""
        unknown = f" · 확인 못 함 {c['unknown']}건" if c["unknown"] else ""
        delta = f" ({c['price_delta']:+,}원)" if c["price_delta"] is not None else ""
        tier = f" · 성능 등급 {c['perf_tier']:g}" if c.get("perf_tier") else ""
        lines.append(f"{i}. {c['name']} · {_won(c['price'])}{delta}{tier}{fail}{unknown}")
    if result.get("note"):
        lines.append(result["note"])
    return "\n".join(lines)


def _spec_value(v, unit: str) -> str:
    if v is None or v == "":
        return "정보 없음"
    if isinstance(v, (list, tuple)):
        v = "/".join(map(str, v))
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v}{unit}"


def compare_parts(result: dict) -> str:
    """`quote_alternatives.compare_parts` 결과를 문장으로 — 스펙 표는 값 차이가 있는 줄 위주로."""
    if result.get("error"):
        return result["error"]
    base = result["baseline"]
    head = f"{result['slot']} 견적: {base['name']}" + (f" {_won(base['price'])}" if base.get("price") is not None else " (가격 없음)")
    lines = [head]
    if not result["candidates"]:
        lines.append("비교할 다른 제품을 찾지 못했습니다.")
    for i, c in enumerate(result["candidates"], 1):
        delta = f" ({c['price_delta']:+,}원)" if c["price_delta"] is not None else ""
        lines.append(f"{i}. {c['name']} {_won(c['price'])}{delta}")
        for r in c["specs"]:
            if r["baseline"] == r["candidate"]:
                continue
            diff = f" ({r['diff']:+g})" if r["diff"] not in (None, 0) else ""
            lines.append(f"   - {r['label']}: 견적 {_spec_value(r['baseline'], r['unit'])} → {_spec_value(r['candidate'], r['unit'])}{diff}")
        if c["incompatible"]:
            lines.append(f"   ⚠ 견적의 다른 부품과 새로 생기는 확정 비호환: {', '.join(c['incompatible'])}")
        for ch in c["compat_changes"]:
            lines.append(f"   · {ch['label']}: {_STATE_TEXT[ch['from']]} → {_STATE_TEXT[ch['to']]}")
        rev = c.get("review") or {}
        lines.append("   리뷰: " + (rev.get("headline") or "정보 없음") + (f" (관측된 리뷰 {rev['total_count']}건)" if rev.get("total_count") else ""))
    b_rev = (base.get("review") or {})
    if b_rev.get("headline"):
        lines.append("견적 부품 리뷰: " + b_rev["headline"])
    for name in result.get("unmatched_targets") or []:
        lines.append(f"'{name}'은(는) 카탈로그에서 찾지 못했습니다.")
    if result.get("note"):
        lines.append(result["note"])
    return "\n".join(lines)
