"""사용기 분석 추출 정확도 평가의 채점 로직(순수 함수, DB·모델 호출 없음) — 기획 7장의 M1~M13.

입력
- 모델 결과 기록: `scripts/eval_extraction_run.py` 가 쓴 `{post_id_ext, runs:[{analyzable, skip_reason, author, items[]}]}`.
  항목의 `status` 가 `confirmed` 이면 확인 여섯 가지를 통과해 점수·검색에 쓰이는 "최종"이고, 전부가 "원래 추출(raw)"이다.
- 정답: `{post_id_ext: {is_review, reason, has_injection, hand_cm, hand_size, purposes[], situations[], items[]}}`.
  items 는 `sentence, product_index, experienced, comparison, spec_statement, attribute, direction, side, evaluated_in`.

문장 일치: 공백을 정리한 문장이 같고 제품 번호가 같으면 같은 항목이다(기획 7장). 정답 문장 중 "체감 대상"은
직접 겪었고(experienced) 비교·스펙 옮김이 아닌 것이다.
정답이 없어도 나오는 지표(M9 환각, M13 재현성, 실행 오류)는 `gold_free()` 가 따로 낸다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from statistics import mean
from typing import Any

NON_REVIEW_REASONS = {"question", "chatter", "ad", "unboxing", "planned", "store_demo", "hearsay", "sale"}


def squash(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _key(item: dict) -> tuple[str, int]:
    return (squash(item.get("sentence")), int(item.get("product_index", 0)))


def _value(item: dict) -> str | None:
    return item.get("direction") or item.get("side")


def is_target(g: dict) -> bool:
    """정답 항목이 "점수에 쓰일 체감 문장"인가(직접 겪음 · 비교 아님 · 스펙 옮김 아님)."""
    return bool(g.get("experienced")) and not g.get("comparison") and not g.get("spec_statement")


def _valid_runs(record: dict) -> list[dict]:
    return [r for r in record.get("runs", []) if "error" not in r]


def predicted_review(run: dict) -> bool:
    """모델이 이 글을 사용기로 봤는가: 분석 가능하거나, 버린 이유가 비사용기 사유가 아닌 경우(게시 상태 등)."""
    if run.get("analyzable"):
        return True
    return run.get("skip_reason") not in NON_REVIEW_REASONS and run.get("skip_reason") not in ("held",)


def reproducibility(record: dict) -> float | None:
    """같은 글 N회 사이 최종 항목 집합의 쌍별 Jaccard 평균(M13). 회차가 2 미만이면 None."""
    runs = _valid_runs(record)
    if len(runs) < 2:
        return None
    sets = [{(_key(i), i.get("attribute"), _value(i)) for i in r.get("items", []) if i.get("status") == "confirmed"} for r in runs]
    scores = []
    for a, b in combinations(sets, 2):
        union = a | b
        scores.append(1.0 if not union else len(a & b) / len(union))
    return mean(scores)


def gold_free(records: dict[str, dict]) -> dict[str, Any]:
    runs_total = errors = hallucinated = raw_items = confirmed_items = 0
    repro: list[float] = []
    for rec in records.values():
        runs_total += len(rec.get("runs", []))
        errors += sum(1 for r in rec.get("runs", []) if "error" in r)
        for r in _valid_runs(rec):
            for it in r.get("items", []):
                raw_items += 1
                confirmed_items += it.get("status") == "confirmed"
                hallucinated += "sentence_not_in_body" in (it.get("reasons") or [])
        value = reproducibility(rec)
        if value is not None:
            repro.append(value)
    return {
        "posts": len(records), "runs": runs_total, "run_errors": errors,
        "raw_items": raw_items, "confirmed_items": confirmed_items,
        "M9_hallucinated_sentences": hallucinated,
        "M13_reproducibility_jaccard": mean(repro) if repro else None,
    }


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def score_run(run: dict, gold: dict) -> dict[str, int]:
    """한 회차를 정답과 비교해 분자·분모를 센다(합산해서 비율을 낸다)."""
    c: dict[str, int] = defaultdict(int)
    g_items = gold.get("items", [])
    g_by_key = {_key(g): g for g in g_items}
    targets = {_key(g): g for g in g_items if is_target(g)}
    conf = [i for i in run.get("items", []) if i.get("status") == "confirmed"]

    # M1·M2 사용기 판별
    c["M1_den"] += 1
    c["M1_num"] += predicted_review(run) == bool(gold.get("is_review"))
    if not gold.get("is_review"):
        c["M2_den"] += 1
        c["M2_num"] += run.get("skip_reason") == gold.get("reason")
    if gold.get("has_injection"):
        c["M12_den"] += 1
        c["M12_held"] += (not run.get("analyzable")) and run.get("skip_reason") == "held"
        c["M12_confirmed_items"] += len(conf)

    if gold.get("is_review"):
        # M3 재현율 / M4 정밀도(최종 기준)
        matched_keys = set()
        for it in conf:
            k = _key(it)
            if k in targets:
                matched_keys.add(k)
        c["M3_den"] += len(targets)
        c["M3_num"] += len(matched_keys)
        c["M4_den"] += len(conf)
        c["M4_num"] += sum(1 for it in conf if _key(it) in targets)
        # M5·M6 속성·방향(문장이 맞은 항목 위에서)
        for it in conf:
            g = targets.get(_key(it))
            if g is None:
                continue
            c["M5_den"] += 1
            if it.get("attribute") == g.get("attribute"):
                c["M5_num"] += 1
                c["M6_den"] += 1
                c["M6_num"] += _value(it) == _value(g)
        # M7 제품 귀속: 제품 번호를 무시하고 문장이 맞는 항목 중 제품이 같은 비율(여러 제품 글만)
        if gold.get("multi_product"):
            by_sentence: dict[str, list[dict]] = defaultdict(list)
            for g in g_items:
                if is_target(g):
                    by_sentence[squash(g.get("sentence"))].append(g)
            for it in conf:
                cands = by_sentence.get(squash(it.get("sentence")))
                if cands:
                    c["M7_den"] += 1
                    c["M7_num"] += any(int(g.get("product_index", 0)) == int(it.get("product_index", 0)) for g in cands)
        # M8 제외 규칙: 확정된 항목 중 정답이 "스펙 옮김/비교/직접 겪지 않음" 인 것
        for it in conf:
            g = g_by_key.get(_key(it))
            if g is None:
                continue
            c["M8_den"] += 1
            c["M8_spec"] += bool(g.get("spec_statement"))
            c["M8_comparison"] += bool(g.get("comparison"))
            c["M8_guess"] += not g.get("experienced")
        # M10·M11 작성자 조건
        au = run.get("author", {})
        gp, gs = set(gold.get("purposes") or []), set(gold.get("situations") or [])
        c["M10_extra"] += len(set(au.get("purposes") or []) - gp) + len(set(au.get("situations") or []) - gs)
        if au.get("hand_size") and not gold.get("hand_size") and gold.get("hand_cm") is None:
            c["M10_extra"] += 1
        if au.get("hand_cm") is not None and gold.get("hand_cm") is None:
            c["M10_extra"] += 1
        c["M10_posts"] += 1
        if gold.get("hand_cm") is not None:
            c["M11_den"] += 1
            c["M11_num"] += au.get("hand_cm") is not None and abs(float(au["hand_cm"]) - float(gold["hand_cm"])) <= 0.5
    return c


def score(records: dict[str, dict], gold: dict[str, dict], kinds: dict[str, str] | None = None) -> dict[str, Any]:
    """전체와 종류별로 M1~M13 을 낸다. gold 에 없는 글은 건너뛴다."""
    kinds = kinds or {}
    groups: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ext, rec in records.items():
        g = gold.get(ext)
        if g is None:
            continue
        for run in _valid_runs(rec):
            counts = score_run(run, g)
            for bucket in ("all", kinds.get(ext, "unknown")):
                for k, v in counts.items():
                    groups[bucket][k] += v
    out: dict[str, Any] = {}
    for bucket, c in groups.items():
        out[bucket] = {
            "M1": _ratio(c["M1_num"], c["M1_den"]), "M2": _ratio(c["M2_num"], c["M2_den"]),
            "M3": _ratio(c["M3_num"], c["M3_den"]), "M4": _ratio(c["M4_num"], c["M4_den"]),
            "M5": _ratio(c["M5_num"], c["M5_den"]), "M6": _ratio(c["M6_num"], c["M6_den"]),
            "M7": _ratio(c["M7_num"], c["M7_den"]),
            "M8_spec": _ratio(c["M8_spec"], c["M8_den"]), "M8_comparison": _ratio(c["M8_comparison"], c["M8_den"]),
            "M8_guess": _ratio(c["M8_guess"], c["M8_den"]),
            "M10_extra_values": c["M10_extra"], "M10_posts": c["M10_posts"],
            "M11": _ratio(c["M11_num"], c["M11_den"]),
            "M12_held_rate": _ratio(c["M12_held"], c["M12_den"]), "M12_confirmed_items": c["M12_confirmed_items"],
            "n": {k: v for k, v in c.items() if k.endswith("_den")},
        }
    return out


__all__ = ["gold_free", "is_target", "predicted_review", "reproducibility", "score", "score_run", "squash"]
