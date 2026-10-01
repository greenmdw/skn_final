"""/lists/* — 사이드바 목록 · S5-a 확정 · S5-b 리포트 · 목표가 알림 (§D-4-3)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header

from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.services import list_history, list_service, notification_service

router = APIRouter(prefix="/lists", tags=["lists"])


@router.get("", response_model=schemas.ListsOut)
def my_lists(principal: Principal = Depends(optional_principal)) -> schemas.ListsOut:
    """사이드바 "내 장바구니" — 로그인 사용자 또는 guest 쿠키 소유분, 최근 수정순."""
    with get_conn() as conn:
        items = list_service.list_conversations(conn, principal)
    return schemas.ListsOut(items=[schemas.ListSummaryOut(**item) for item in items])


@router.patch("/{list_id}", response_model=schemas.ListSummaryOut)
def rename(
    list_id: UUID, body: schemas.ListRenameIn, principal: Principal = Depends(optional_principal)
) -> schemas.ListSummaryOut:
    with get_conn() as conn:
        summary = list_service.rename(conn, list_id, principal, name=body.name)
    return schemas.ListSummaryOut(**summary)


@router.delete("/{list_id}", status_code=204)
def delete(list_id: UUID, principal: Principal = Depends(optional_principal)) -> None:
    with get_conn() as conn:
        list_service.delete(conn, list_id, principal)


@router.post("/{list_id}/confirm", response_model=schemas.ReportOut)
def confirm(
    list_id: UUID, body: schemas.ConfirmIn, if_match: int | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(optional_principal),
) -> schemas.ReportOut:
    """draft → confirmed. 비로그인이면 401 (프론트가 로그인 모달)."""
    with get_conn() as conn:
        report = list_service.confirm(
            conn, list_id, principal,
            name=body.name, planned_purchase_at=body.planned_purchase_at,
            target_amount=body.target_amount, memo=body.memo, if_match=if_match,
        )
    return schemas.ReportOut(**report)


@router.get("/{list_id}/report", response_model=schemas.ReportOut)
def report(list_id: UUID, revision: int | None = None,
           principal: Principal = Depends(optional_principal)) -> schemas.ReportOut:
    """확정 견적서. revision(번호)을 주지 않으면 가장 최근 확정본."""
    with get_conn() as conn:
        report = list_service.get_report(conn, list_id, principal, revision)
    return schemas.ReportOut(**report)


@router.post("/{list_id}/revisions", response_model=schemas.ConditionState)
def new_revision(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.ConditionState:
    """확정한 견적의 조건으로 새 견적서(draft revision)를 시작한다. 이후 /session/{list_id}/* 는 새 견적서에 쓴다."""
    with get_conn() as conn:
        state = list_service.new_revision(conn, list_id, principal)
    return schemas.ConditionState(**state)


@router.delete("/{list_id}/reports/{revision_no}", response_model=schemas.ConditionState)
def delete_report(
    list_id: UUID, revision_no: int, principal: Principal = Depends(optional_principal)
) -> schemas.ConditionState:
    """견적서(확정된 revision) 하나만 삭제한다(개발요청 10번). 대화·다른 견적서는 그대로 둔다."""
    with get_conn() as conn:
        state = list_service.delete_report(conn, list_id, principal, revision_no)
    return schemas.ConditionState(**state)


@router.patch("/{list_id}/reports/{revision_no}", response_model=schemas.ReportOut)
def rename_report(
    list_id: UUID, revision_no: int, body: schemas.ReportRenameIn,
    principal: Principal = Depends(optional_principal),
) -> schemas.ReportOut:
    """견적서 하나의 이름만 바꾼다(개발요청 10번) — 대화 이름(`PATCH /lists/{id}`)과 별개."""
    with get_conn() as conn:
        report = list_service.rename_report(conn, list_id, principal, revision_no, body.name)
    return schemas.ReportOut(**report)


@router.get("/{list_id}/history", response_model=schemas.ListHistoryOut)
def history(list_id: UUID, revision: int | None = None,
            principal: Principal = Depends(optional_principal)) -> schemas.ListHistoryOut:
    """견적 리스트 히스토리 — 요약 문장은 LLM 호출이 있어 리포트와 따로 부른다(리포트 로딩을 늦추지 않는다)."""
    with get_conn() as conn:
        found, events = list_service.get_history_events(conn, list_id, principal, revision)
    return schemas.ListHistoryOut(**list_history.render(list_id, found, events))


@router.post("/{list_id}/alert")
def set_alert(
    list_id: UUID, body: schemas.AlertIn, principal: Principal = Depends(optional_principal)
) -> dict:
    """목표가 추적 생성/갱신."""
    with get_conn() as conn:
        result = list_service.set_alert(
            conn, list_id, principal, enabled=body.enabled, target_amount=body.target_amount
        )
    return {"price_watch": schemas.PriceWatchOut(**result["price_watch"]).model_dump()}


@router.get("/{list_id}/alert", response_model=schemas.PriceWatchOut)
def get_alert(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.PriceWatchOut:
    """목표가 추적 현재 상태 — 지금 카탈로그 관측가 기준 총액·목표가·도달 여부·최근 판정 시각."""
    with get_conn() as conn:
        status = notification_service.get_watch_status(conn, list_id, principal)
    return schemas.PriceWatchOut(**status)
