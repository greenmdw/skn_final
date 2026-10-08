"""/session HTTP handlers."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.clients.llm_guard import llm_request_slot
from src.db import get_conn
from src.errors import NotFound
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_runner, recommendation_service, session_service

router = APIRouter(prefix="/session", tags=["session"])

@router.post("", response_model=schemas.SessionOut)
def create(response: Response, principal: Principal = Depends(optional_principal)) -> schemas.SessionOut:
    with get_conn() as conn:
        result = session_service.create_session(conn, principal)
    response.set_cookie(
        "truefit_guest", result["browser_token"],
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180,
    )
    return schemas.SessionOut(list_id=result["list_id"])

# /{list_id} 보다 먼저 등록해야 한다 — 아니면 "previous"가 UUID 검증에 걸려 422가 난다.
@router.get("/previous", response_model=schemas.PreviousLookupOut)
def previous(
    category: str,
    mode: str | None = None,
    exclude: UUID | None = None,
    principal: Principal = Depends(optional_principal),
) -> schemas.PreviousLookupOut:
    with get_conn() as conn:
        found = session_service.previous_conditions(conn, principal, category, mode, exclude)
        hint = session_service.preference_hint(conn, principal, category)
    return schemas.PreviousLookupOut(previous=found, preference_hint=hint)

@router.post("/{list_id}/preference-hint/{signal_id}/respond")
def preference_hint_respond(
    list_id: UUID, signal_id: UUID, body: schemas.PreferenceHintRespondIn,
    principal: Principal = Depends(optional_principal),
) -> dict:
    with get_conn() as conn:
        return session_service.respond_preference_hint(conn, list_id, signal_id, body.accepted, principal)

@router.get("/{list_id}", response_model=schemas.ConditionState)
def get_session(
    list_id: UUID,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.get_session_state(conn, list_id, principal))

@router.post("/{list_id}/category", response_model=schemas.ConditionState)
def choose_category(
    list_id: UUID,
    body: schemas.CategoryIn,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.choose_category(
            conn, list_id, body.category, body.mode, principal,
        ))

@router.patch("/{list_id}/slot", response_model=schemas.ConditionState)
def patch_slot(
    list_id: UUID,
    body: schemas.SlotPatchIn,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.patch_slot(
            conn, list_id, body.field, body.value, principal,
        ))

@router.post("/{list_id}/message", response_model=schemas.ConditionState)
def message(
    list_id: UUID,
    body: schemas.MessageIn,
    principal: Principal = Depends(optional_principal),
    _slot: None = Depends(llm_request_slot),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_message(conn, list_id, body.text, principal))

@router.post("/{list_id}/answer", response_model=schemas.ConditionState)
def answer(
    list_id: UUID,
    body: schemas.AnswerIn,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.handle_answer(
            conn, list_id, body.question_id, body.selected, principal,
        ))

@router.post("/{list_id}/resume", response_model=schemas.ConditionState)
def resume(
    list_id: UUID,
    body: schemas.ResumeIn,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.resume_previous(conn, list_id, body.from_list_id, principal))

@router.post("/{list_id}/reset", response_model=schemas.ConditionState)
def reset(
    list_id: UUID,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.reset_conditions(conn, list_id, principal))

@router.post("/{list_id}/recommend", response_model=schemas.RecommendAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
def recommend(
    list_id: UUID,
    body: schemas.RecommendIn = schemas.RecommendIn(),
    background_tasks: BackgroundTasks = None,
    principal: Principal = Depends(optional_principal),
) -> schemas.RecommendAcceptedOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        accepted = recommendation_service.start_recommendation(
            conn,
            revision["id"],
            strategy=body.strategy or "default",
        )
    background_tasks.add_task(recommendation_runner.dispatch, revision["id"], UUID(accepted["run_id"]))
    return schemas.RecommendAcceptedOut(**accepted)

@router.get("/{list_id}/result", response_model=schemas.RecommendResultOut)
def result(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.get_stored_result(conn, revision["id"])
    if stored is None:
        raise NotFound("추천 실행 결과가 없습니다. 먼저 /recommend 를 호출하세요.")
    return schemas.RecommendResultOut(**stored)

@router.get("/{list_id}/previous-comparison", response_model=schemas.PreviousComparisonOut)
def previous_comparison(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.PreviousComparisonOut:
    from src.services.previous_compare import compare_with_previous
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        return schemas.PreviousComparisonOut(**compare_with_previous(conn, revision["id"]))

@router.patch("/{list_id}/items/{item_id}", response_model=schemas.RecommendResultOut)
def patch_item(list_id: UUID, item_id: UUID, body: schemas.ItemPatchIn, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.patch_item(conn, revision["id"], item_id, selected=body.selected, qty=body.qty, timing=None, user_id=principal.user_id)
    return schemas.RecommendResultOut(**stored)

@router.get("/{list_id}/items/{item_id}/alternatives", response_model=schemas.AlternativesOut)
def alternatives(
    list_id: UUID,
    item_id: UUID,
    principal: Principal = Depends(optional_principal),
) -> schemas.AlternativesOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.list_alternatives(conn, revision["id"], item_id)
    return schemas.AlternativesOut(**stored)

@router.post("/{list_id}/items/{item_id}/swap", response_model=schemas.RecommendResultOut)
def swap(list_id: UUID, item_id: UUID, body: schemas.SwapIn, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.swap_item(conn, revision["id"], item_id, UUID(body.candidate_id), user_id=principal.user_id)
    return schemas.RecommendResultOut(**stored)

@router.post("/{list_id}/peripherals/recommend", response_model=schemas.PeripheralsOut)
def recommend_peripherals(
    list_id: UUID, body: schemas.PeripheralsRecommendIn, principal: Principal = Depends(optional_principal),
) -> schemas.PeripheralsOut:
    """주변기기(모니터·키보드·마우스·스피커) 추천 — 개발요청 6번. PC 견적 대화 없이 바로 호출할 수
    있다. `pc_list_id`를 주면 그 PC 견적의 해상도를 묶어 모니터 교차검사를 추가로 켠다."""
    from src.services import peripherals_service

    with get_conn() as conn:
        session_service._owned(PlanRepo(conn), list_id, principal)
        pc_context = (
            peripherals_service.pc_context_from_list(conn, UUID(body.pc_list_id), principal)
            if body.pc_list_id else None
        )
        payload = peripherals_service.recommend(conn, body, pc_context)
    return schemas.PeripheralsOut(**payload)

@router.post("/{list_id}/result-message", response_model=schemas.ResultMessageOut)
def result_message(
    list_id: UUID,
    body: schemas.ResultMessageIn,
    principal: Principal = Depends(optional_principal),
    _slot: None = Depends(llm_request_slot),
) -> schemas.ResultMessageOut:
    with get_conn() as conn:
        revision = session_service._owned(PlanRepo(conn), list_id, principal)
        stored = recommendation_service.handle_result_message(conn, revision["id"], body.text, user_id=principal.user_id)
    return schemas.ResultMessageOut(**stored)

@router.post("/{list_id}/spec-file", response_model=schemas.ConditionState)
def spec_file(
    list_id: UUID,
    body: schemas.SpecFileIn,
    principal: Principal = Depends(optional_principal),
    _slot: None = Depends(llm_request_slot),
) -> schemas.ConditionState:
    with get_conn() as conn:
        return schemas.ConditionState(**session_service.attach_spec_file(
            conn, list_id, body.file_name, body.content, principal,
        ))
