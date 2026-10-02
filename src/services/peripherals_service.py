"""주변기기 추천 — 세션 API 노출 (개발요청 6번).

`src/engine/peripheral_select.run_peripherals`·`peripheral_payload`는 이미 완성돼 있다
(§3.3 E8~E13) — 이 파일은 그 엔진을 HTTP로 잇는 얇은 서비스 계층일 뿐, 하드/소프트 조건
매칭·랭킹·모니터 교차검사 같은 판단 로직은 하나도 새로 만들지 않는다.

PC 견적과 독립적으로 호출할 수 있다(ChoosePage "/peripherals" 입구) — `pc_list_id`를 주면
그 PC 견적의 해상도를 pc_context로 묶어 모니터 교차검사를 추가로 켠다(C안 + 선택적 PC 맥락
결합). DB 쓰기가 없는 순수 계산이라 PC 추천(`POST .../recommend` → `GET .../result` 폴링)과
달리 요청 한 번으로 끝난다.
"""
from __future__ import annotations

from uuid import UUID

from src.auth.deps import Principal
from src.errors import NotFound


def pc_context_from_list(conn, pc_list_id: UUID, principal: Principal) -> dict | None:
    """pc_list_id가 principal 소유의 PC(컴퓨터) 견적이면 그 해상도를 pc_context로 낸다.

    GPU의 HDMI/DP 포트 스펙(`config/peripherals.yaml`의 `verify.gpu_keys`)은 지금
    `catalog.gpu_spec`에 해당 컬럼이 아예 없어 늘 None이다 — 모니터 교차검사는 그 축만
    "확인 필요"로 남는다(정보 없음을 틀렸다고 단정하지 않는 기존 원칙과 같다).
    소유가 아니거나 못 찾으면 조용히 None — 독립 추천으로 그냥 진행한다(이 필드는 선택이다)."""
    from src.repo.plan_repo import PlanRepo
    from src.services.session_service import _owned

    try:
        revision = _owned(PlanRepo(conn), pc_list_id, principal)
    except NotFound:
        return None
    cvals = {r["condition_key"]: r["value"].get("value")
             for r in PlanRepo(conn).load_full(revision["id"])["conditions"]}
    if cvals.get("category") != "computer":
        return None
    return {"resolution": cvals.get("resolution"), "gpu_specs": None}


def recommend(conn, body, pc_context: dict | None) -> dict:
    """요청 바디(kinds·budget_max·purpose 등)를 run_peripherals()의 조건 dict로 옮겨
    돌리고, 공개 계약 모양(peripheral_payload)으로 낸다.

    `pc_context["resolution"]`은 `run_peripherals`가 교차검사에만 쓰고, 모니터 요구사양
    (hard filter의 해상도·주사율)은 `values["resolution"]`만 본다 — 둘이 서로 안 통해서,
    PC가 QHD_165인데도 모니터 요구사양은 기본값(FHD_144)으로 떨어지는 결과가 났다(실측
    확인). body가 resolution을 안 주면 pc_context 쪽을 대신 써서 "PC 견적 이후 주변기기도
    같이 보기"가 그 PC의 해상도를 그대로 이어받게 한다 — body가 주면 그게 우선(명시가 추정을 이긴다)."""
    from src.engine.peripheral_payload import peripheral_payload
    from src.engine.peripheral_select import run_peripherals
    from src.repo.catalog_repo import load_peripheral_candidates
    from src.services.review_ranking import score_peripheral_candidates

    resolution = body.resolution or (pc_context or {}).get("resolution")
    values = {
        "peripherals": body.kinds,
        "peripheral_budget_max": body.budget_max,
        "purpose": body.purpose,
        "priority": body.priority,
        "noise_sensitive": body.noise_sensitive,
        "resolution": resolution,
    }
    candidates = load_peripheral_candidates(conn)
    requested_candidates = {kind: candidates.get(kind, []) for kind in body.kinds}
    score_peripheral_candidates(conn, requested_candidates, values, catalog_source="db")
    result = run_peripherals(
        values, candidates, log=lambda *_: None, pc_context=pc_context,
        require_review_details=True,
    )
    return peripheral_payload(result)
