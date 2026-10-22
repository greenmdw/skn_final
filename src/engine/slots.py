"""[1] 조건 경로 → Slots.

`session_service`가 대화로 채운 조건(dict)을 [2]가 읽는 `Slots`로 바꾼다. `stage1_intent.run`
(시나리오 + `mock_slot_fill`)과 나란히 두는 두 번째 경로다 — 둘 다 같은 `Slots.values`를
만들어야 [2] 이후가 갈라지지 않는다(E3, `tests/test_slots_equivalence.py`).

`src/services/recommendation_service.py`에 있던 `_slots_from_conditions`를 그대로 옮긴 것이다.
로직은 바꾸지 않았다.
"""
from __future__ import annotations

from src.dto import Slots


def slots_from_conditions(category: str, cat_def: dict, values: dict) -> Slots:
    defaults = cat_def.get("defaults") or {}
    assumed = {k: v for k, v in defaults.items() if values.get(k) in (None, [], "")}
    full = {**assumed, **values}
    return Slots(
        category=category, mode=full.get("mode", (cat_def.get("modes") or ["build"])[0]),
        objective_text="(대화로 수집됨)", values=full,
        assumed_keys=list(assumed.keys()), missing=[],
    )
