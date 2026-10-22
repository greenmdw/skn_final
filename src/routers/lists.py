"""/lists/* — 사이드바 목록 · S5-a 확정 · S5-b 리포트 (§D-4-3)."""
from __future__ import annotations

from uuid import UUID

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, Field

from src import schemas
from src.auth.deps import Principal, optional_principal
from src.auth import ratelimit
from src.config import ME_WRITE_LIMIT_PER_MIN
from src.db import get_conn
from src.errors import RateLimited
from src.services import list_history, list_service, me_service

router = APIRouter(prefix="/lists", tags=["lists"])


@router.get("", response_model=schemas.ListsOut)
def my_lists(
    principal: Principal = Depends(optional_principal),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> schemas.ListsOut:
    """사이드바 "내 장바구니" — 로그인 사용자 또는 guest 쿠키 소유분, 최근 수정순.

    limit/offset은 선택이다 — 안 주면(기본) 지금까지처럼 전량 반환한다. 리스트가 아주 많은
    계정에서 전량 반환이 느려질 수 있어(발견 사항) 필요할 때 자를 수 있게만 열어 둔 것으로,
    기본 동작은 바뀌지 않는다."""
    with get_conn() as conn:
        items = list_service.list_conversations(conn, principal, limit=limit, offset=offset)
    return schemas.ListsOut(items=[schemas.ListSummaryOut(**item) for item in items])


class ExtrasIn(BaseModel):
    extras: dict[str, Any] = Field(description="견적서에 붙일 화면 전용 값 전부(조건 문장·책상 치수·점검 스냅샷 …). 모양은 서버가 보지 않는다")


def _write_limit(principal: Principal) -> None:
    if principal.user_id is not None and not ratelimit.allow(f"me-write:{principal.user_id}", limit=ME_WRITE_LIMIT_PER_MIN, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")


@router.get("/extras")
def all_extras(principal: Principal = Depends(optional_principal)) -> dict:
    """내 목록 전체의 부가 정보를 한 번에(사이드바·마이페이지용). `{items: {list_id: {extras, updated_at}}}`, 최근 수정순 200개."""
    with get_conn() as conn:
        return me_service.list_extras(conn, principal)


@router.get("/{list_id}/extras")
def get_extras(list_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    """이 견적서의 부가 정보. 저장한 적이 없으면 `extras: null`. 로그인한 소유자만(아니면 401·404)."""
    with get_conn() as conn:
        return me_service.get_extras(conn, principal, list_id)


@router.put("/{list_id}/extras")
def put_extras(list_id: UUID, body: ExtrasIn, principal: Principal = Depends(optional_principal)) -> dict:
    """통째로 교체한다(문서 256KB·깊이 32까지)."""
    _write_limit(principal)
    with get_conn() as conn:
        return me_service.put_extras(conn, principal, list_id, body.extras)


@router.delete("/{list_id}/extras", status_code=status.HTTP_204_NO_CONTENT)
def delete_extras(list_id: UUID, principal: Principal = Depends(optional_principal)) -> Response:
    _write_limit(principal)
    with get_conn() as conn:
        me_service.delete_extras(conn, principal, list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{list_id}", response_model=schemas.ListSummaryOut)
def rename(
    list_id: UUID, body: schemas.ListRenameIn, principal: Principal = Depends(optional_principal)
) -> schemas.ListSummaryOut:
    with get_conn() as conn:
        summary = list_service.rename(conn, list_id, principal, name=body.name)
    return schemas.ListSummaryOut(**summary)


@router.delete("/{list_id}", status_code=204)
def delete(list_id: UUID, permanent: bool = Query(default=False), principal: Principal = Depends(optional_principal)) -> None:
    """대화 삭제. permanent=true 면 보관 기간 없이 바로 영구 삭제한다(로그인한 소유자만)."""
    with get_conn() as conn:
        list_service.delete(conn, list_id, principal, permanent=permanent)


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
            peripherals=[p.model_dump() for p in body.peripherals],
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
def new_revision(
    list_id: UUID, body: schemas.NewRevisionIn | None = None,
    principal: Principal = Depends(optional_principal),
) -> schemas.ConditionState:
    """확정한 견적의 조건으로 새 견적서(draft revision)를 시작한다. 이후 /session/{list_id}/* 는 새 견적서에 쓴다.

    개발요청 14번 — body에 `from_revision_no`를 주면 가장 최근이 아니라 그 번호의 확정
    견적서를 원본으로 복사한다(한 대화에 견적서가 여럿일 때 예전 것을 고치는 경우)."""
    with get_conn() as conn:
        state = list_service.new_revision(
            conn, list_id, principal, from_revision_no=body.from_revision_no if body else None
        )
    return schemas.ConditionState(**state)


@router.delete("/{list_id}/reports/{revision_no}", response_model=schemas.ConditionState)
def delete_report(
    list_id: UUID, revision_no: int, permanent: bool = Query(default=False), principal: Principal = Depends(optional_principal)
) -> schemas.ConditionState:
    """견적서(확정된 revision) 하나만 삭제한다(개발요청 10번). 대화·다른 견적서는 그대로 둔다."""
    with get_conn() as conn:
        state = list_service.delete_report(conn, list_id, principal, revision_no, permanent=permanent)
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
        found, journey = list_service.get_history(conn, list_id, principal, revision)
    return schemas.ListHistoryOut(**list_history.render(list_id, found, journey))
