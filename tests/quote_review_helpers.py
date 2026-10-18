"""받은 견적 점검 테스트가 분석된 견적(대화)을 만드는 공통 도구 — 예전 `POST /pc/reviews` 를 지운 뒤 새 초안 흐름(텍스트 → 분석)으로 만든다."""
from __future__ import annotations

import json


def create_review(client, specs: dict[str, str], conditions: dict | None = None) -> dict:
    """부품군별 문구로 초안을 만들고 분석해 결과를 돌려준다(list_id 포함). 응답이 201 이 아니거나 분석이 실패하면 AssertionError."""
    text = "\n".join(f"{slot}: {value}" for slot, value in specs.items())
    data = {"text": text}
    if conditions:
        data["conditions"] = json.dumps(conditions)
    created = client.post("/pc/review-drafts", data=data)
    assert created.status_code == 201, created.text
    draft = created.json()
    analysed = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={})
    assert analysed.status_code == 200, analysed.text
    return {**analysed.json(), "list_id": draft["draft_id"]}
