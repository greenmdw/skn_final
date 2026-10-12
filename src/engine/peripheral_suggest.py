"""주변기기 "더 맞추기" 칩 제안 — 눌렀을 때 지금 보이는 순서를 바꾸는 것만 내보낸다(견적 입력 설계 6.2).

추천 결과 아래에 최대 3개를 제안한다. 규칙은 설계 문서 그대로다.

- 후보는 `config/peripherals.yaml` 의 `adjust_chips` 에 종류별로 있다.
- **지금 보이는 결과의 순서를 바꾸는 칩만** 낸다. 칩을 더해 같은 조건으로 다시 순위를 매겨(후보 목록과 리뷰 점수는
  그대로 쓰므로 DB·언어 모델을 부르지 않는다) 1위와 대안 2개의 순서가 달라지는지 본다.
- 이미 말한 조건의 칩은 내지 않는다.
- 순서를 많이 바꾸는 칩이 먼저, 같으면 설정 순서다.

이 모듈은 칩을 *눌렀을 때* 무엇이 바뀌는지만 계산한다. 칩을 누른 뒤의 추천은 화면이 `add` 를 입력에 더해
추천 API 를 다시 부르면 된다(문장 해석을 다시 부르지 않는다).
"""
from __future__ import annotations

from itertools import zip_longest
from typing import Any

from src.dto import Candidate, PeripheralPick, PeripheralResult
from src.engine import peripheral_intent
from src.engine.peripheral_intent import Interpretation
from src.engine.peripheral_rules import adjust_chips, load_peripheral_rules
from src.engine.peripheral_select import run_peripherals

CHIP_LIMIT = 3


def _visible_order(pick: PeripheralPick) -> list[str]:
    """사용자에게 보이는 순서: 1위 다음에 대안들."""
    return [pick.candidate.product_key, *(c.product_key for c in pick.alternatives)]


def _already_said(add: dict[str, Any], interp: Interpretation, kind: str) -> bool:
    said_purposes = {*interp.purposes, *interp.situations}
    stated = set(interp.stated.get(kind, []))
    return (set(add.get("purposes", [])) | set(add.get("situations", [])) <= said_purposes
            and set(add.get("stated", [])) <= stated)


def _with_chip(interp: Interpretation, kind: str, add: dict[str, Any], rules: dict) -> Interpretation:
    extra = peripheral_intent.sanitize({
        "kinds": [kind],
        "purposes": add.get("purposes", []),
        "situations": add.get("situations", []),
        "stated": {kind: add["stated"]} if add.get("stated") else {},
    }, rules)
    return peripheral_intent.merge(interp, extra)


def suggest_chips(
    values: dict, interp: Interpretation, candidates: dict[str, list[Candidate]], base: PeripheralResult,
    rules: dict | None = None, *, pc_context: dict | None = None, limit: int = CHIP_LIMIT,
    require_review_details: bool = False,
) -> list[dict[str, Any]]:
    """`base` 는 같은 입력으로 이미 돌린 결과다. 반환: [{kind, id, label, add, moved}] — `add` 는 화면이 입력에
    그대로 더하면 되는 모양({purposes, situations, stated: {kind: [...]}}), `moved` 는 바뀌는 자리 수다."""
    rules = rules or load_peripheral_rules()
    if base.status != "ready":
        return []
    base_orders = {pick.kind: _visible_order(pick) for pick in base.picks}

    found: list[tuple[int, int, dict[str, Any]]] = []
    position = 0
    for kind in peripheral_intent.kinds_all_order(list(base_orders)):
        for chip in adjust_chips(kind, rules):
            position += 1
            if _already_said(chip["add"], interp, kind):
                continue
            trial = _with_chip(interp, kind, chip["add"], rules)
            trial_values = {**values, "peripheral_intent": trial,
                            "peripheral_resolved": peripheral_intent.resolve(trial, rules)}
            result = run_peripherals(trial_values, candidates, lambda *_: None, pc_context=pc_context,
                                     require_review_details=require_review_details)
            after = next((p for p in result.picks if p.kind == kind), None)
            if after is None:
                continue
            moved = sum(1 for a, b in zip_longest(base_orders[kind], _visible_order(after)) if a != b)
            if moved == 0:
                continue          # 눌러도 순서가 안 바뀌는 칩은 내지 않는다
            found.append((moved, position, {
                "kind": kind,
                "id": chip["id"],
                "label": chip["label"],
                "add": {
                    "purposes": list(chip["add"].get("purposes", [])),
                    "situations": list(chip["add"].get("situations", [])),
                    "stated": {kind: list(chip["add"]["stated"])} if chip["add"].get("stated") else {},
                },
                "moved": moved,
            }))
    found.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in found[:limit]]
