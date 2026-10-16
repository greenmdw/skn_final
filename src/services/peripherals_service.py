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
from src.dto import PeripheralResult
from src.errors import NotFound


def pc_context_from_list(conn, pc_list_id: UUID, principal: Principal) -> dict | None:
    """pc_list_id가 principal 소유의 PC(컴퓨터) 견적이면 그 해상도를 pc_context로 낸다.

    `purpose` 는 그 PC 견적의 용도(game 등)다 — 모니터 요구사양의 주사율 상향(4K+game)과 PC 용도에서 풀리는 주변기기 목적이
    읽는다. 예전에는 요청 바디가 직접 받던 값이다.
    `gpu_specs` 는 그 PC 견적에서 선택된 GPU 의 스펙이다(HDMI/DP 버전·USB-C 영상 출력은 0016, B-9).
    선택 GPU 가 없거나 단자 값이 비어 있으면 모니터 교차검사는 그 축만 "확인 필요"로 남는다
    (정보 없음을 틀렸다고 단정하지 않는 기존 원칙과 같다).
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
    gpu_specs = _selected_gpu_specs(conn, revision["id"])
    return {"resolution": cvals.get("resolution"), "gpu_specs": gpu_specs,
            "integrated_graphics": gpu_specs is None and _gpu_left_out(conn, revision["id"]),
            "purpose": cvals.get("purpose")}


def _gpu_left_out(conn, revision_id: UUID) -> bool:
    """PC 견적이 신규 조립 규칙(용도 배분 GPU 0%)으로 GPU 를 일부러 뺐는가 — 저장된 '견적 구성 슬롯' 기록으로 본다."""
    from src.engine import omitted_slots
    from src.repo.engine_repo import EngineRepo

    erepo = EngineRepo(conn)
    run = erepo.get_latest_run_state(revision_id)
    if run is None or run["status"] != "completed":
        return False
    return "GPU" in omitted_slots.omitted_from_step(erepo.get_run_step(run["id"], omitted_slots.OMITTED_SLOTS_STEP))


def _selected_gpu_specs(conn, revision_id: UUID) -> dict | None:
    """PC 견적의 최신 완료 추천에서 선택된 GPU 의 스펙(`hdmi_version`·`dp_version`·`usb_c_video_out` 포함).

    완료된 추천이 없거나 GPU 를 고르지 않았으면 None — 모니터 교차검사는 그 축을 "확인 필요"로 둔다."""
    from src.repo.catalog_repo import load_specs_by_variant
    from src.repo.engine_repo import EngineRepo

    erepo = EngineRepo(conn)
    run = erepo.get_latest_run_state(revision_id)
    if run is None or run["status"] != "completed":
        return None
    gpu = next((c for c in erepo.get_candidates(run["id"])
                if c.get("product_type") == "gpu" and c.get("selected")), None)
    if gpu is None:
        return None
    return load_specs_by_variant(conn, [("gpu", str(gpu["variant_id"]))]).get(str(gpu["variant_id"])) or None


def _intent_from_body(body, pc_purpose: str | None = None):
    """요청 바디의 견적 입력(목적·상황·직접 말한 조건·종류별 예산·강조·브랜드)을 정해진 목록 안의 값으로 정리한다.

    `pc_purpose` 는 묶은 PC 견적의 용도(`pc_context["purpose"]`)다 — 목적 코드로 옮겨 `purposes` 에 더한다. 예전 입력
    (`purpose`·`priority`·`noise_sensitive`)은 없앴다. 목록에 없는 이름은 버리고 이름만 돌려준다
    (오류로 내지 않고 안내로 돌려주는 원칙, 견적 입력 설계 8장).
    """
    from src.engine import peripheral_intent

    raw = {
        "kinds": list(body.kinds),
        "purposes": [*body.purposes, *peripheral_intent.from_pc_purpose(pc_purpose)],
        "situations": list(body.situations),
        "stated": body.stated,
        "budget": body.kind_budget,
        "budget_min": body.kind_budget_min,
        "emphasis": body.emphasis,
        "brand_like": body.brand_like,
        "brand_avoid": body.brand_avoid,
        "hand_size": body.hand_size,
    }
    interp = peripheral_intent.sanitize(raw)

    def _names(per_kind: dict) -> set[str]:
        return {n for items in per_kind.values() for n in items}

    sent = {*body.purposes, *body.situations, *(c for ids in body.stated.values() for c in ids),
            *_names(body.emphasis), *_names(body.brand_like), *_names(body.brand_avoid)}
    kept = {*interp.purposes, *interp.situations, *(c for ids in interp.stated.values() for c in ids),
            *_names(interp.emphasis), *_names(interp.brand_like), *_names(interp.brand_avoid)}
    ignored = sorted(sent - kept)
    return interp, ignored


def recommend(conn, body, pc_context: dict | None) -> dict:
    """요청 바디를 추천으로 돌려 공개 계약 모양(peripheral_payload)으로 낸다. 자세한 설명은 `recommend_detailed`."""
    return recommend_detailed(conn, body, pc_context)[0]


def recommend_detailed(conn, body, pc_context: dict | None) -> tuple[dict, "PeripheralResult"]:
    """요청 바디(kinds·budget_max·purpose 등)를 run_peripherals()의 조건 dict로 옮겨
    돌리고, 공개 계약 모양(peripheral_payload)과 엔진 결과를 함께 낸다. 채팅 질문 답변(peripheral_chat_service)이 스펙 값을
    엔진 결과의 후보에서 읽으려고 둘 다 받는다.

    `pc_context` 는 `pc_context_from_list` 가 낸 {resolution, gpu_specs, purpose} 다. `purpose`(PC 견적 용도)는 모니터 요구사양의
    주사율 상향과 주변기기 목적 풀이에, 해상도는 아래 설명대로 쓰인다.

    `pc_context["resolution"]`은 `run_peripherals`가 교차검사에만 쓰고, 모니터 요구사양
    (hard filter의 해상도·주사율)은 `values["resolution"]`만 본다 — 둘이 서로 안 통해서,
    PC가 QHD_165인데도 모니터 요구사양은 기본값(FHD_144)으로 떨어지는 결과가 났다(실측
    확인). body가 resolution을 안 주면 pc_context 쪽을 대신 써서 "PC 견적 이후 주변기기도
    같이 보기"가 그 PC의 해상도를 그대로 이어받게 한다 — body가 주면 그게 우선(명시가 추정을 이긴다)."""
    from src.engine import peripheral_intent
    from src.engine.peripheral_payload import peripheral_payload
    from src.engine.peripheral_select import run_peripherals
    from src.engine.peripheral_suggest import suggest_chips
    from src.services import peripheral_post_pipeline
    from src.repo.catalog_repo import load_peripheral_candidates
    from src.services.review_ranking import score_peripheral_candidates

    resolution = body.resolution or (pc_context or {}).get("resolution")
    pc_purpose = (pc_context or {}).get("purpose")
    interp, ignored = _intent_from_body(body, pc_purpose)
    candidates = load_peripheral_candidates(conn)
    requested_candidates = {kind: candidates.get(kind, []) for kind in body.kinds}
    values = {
        "peripherals": body.kinds,
        "peripheral_budget_max": body.budget_max,
        "peripheral_kind_budget": interp.budget,
        "peripheral_kind_budget_min": interp.budget_min,
        "peripheral_intent": interp,
        "peripheral_resolved": peripheral_intent.resolve(interp),
        # 선호·기피 브랜드와 강조 축은 목록 안의 값으로 정리한 해석에서 온다(예전 입력과 같은 경로).
        "peripheral_brand_like": {k: list(v) for k, v in interp.brand_like.items() if k in body.kinds},
        "peripheral_brand_avoid": {k: list(v) for k, v in interp.brand_avoid.items() if k in body.kinds},
        "peripheral_emphasis": {k: list(v) for k, v in interp.emphasis.items() if k in body.kinds},
        # 사용기 분석이 쌓은 근거(종류 → 관측). 분석 결과가 없으면 비어 있고 체감 점수는 외부 리뷰만으로 계산된다.
        "peripheral_feel_observations": peripheral_post_pipeline.current_observations(
            conn, [c.product_id for group in requested_candidates.values() for c in group if c.product_id]),
        # purpose 는 monitor.hard 의 주사율 상향(4K+game)과 리뷰 점수가, noise_sensitive 는 외부 리뷰 점수의 소리 속성 중요도가
        # 읽는 PC 견적 조건 이름이다. 새 입력에서는 purpose 를 묶은 PC 견적에서, noise_sensitive 를 "조용해야 함"
        # 상황(quiet_place)에서 얻는다 — 같은 말을 두 번 하게 하지 않는다. priority 는 더 쓰지 않는다.
        "purpose": pc_purpose,
        "priority": None,
        "noise_sensitive": True if "quiet_place" in interp.situations else None,
        "resolution": resolution,
    }
    score_peripheral_candidates(conn, requested_candidates, values, catalog_source="db")
    result = run_peripherals(
        values, candidates, log=lambda *_: None, pc_context=pc_context,
        require_review_details=True,
    )
    payload = peripheral_payload(result)
    payload["ignored_inputs"] = ignored
    payload["adjust_chips"] = suggest_chips(values, interp, candidates, result, pc_context=pc_context,
                                          require_review_details=True)
    return payload, result
