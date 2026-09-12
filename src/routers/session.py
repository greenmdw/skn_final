"""/session HTTP handlers."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends
from src import schemas
from src.auth.deps import Principal, optional_principal
from src.db import get_conn
from src.services import session_service

router = APIRouter(prefix="/session", tags=["session"])

@router.post("", response_model=schemas.SessionOut)
def create(principal: Principal = Depends(optional_principal)) -> schemas.SessionOut:
    with get_conn() as conn:
        return schemas.SessionOut(**session_service.create_session(conn, principal))

@router.post("/{list_id}/category", response_model=schemas.ConditionStateOut)
def choose_category(list_id: UUID, body: schemas.CategoryIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionStateOut:
    with get_conn() as conn:
        return schemas.ConditionStateOut(**session_service.choose_category(conn, list_id, body.category, body.mode, principal))

@router.patch("/{list_id}/slot", response_model=schemas.ConditionStateOut)
def patch_slot(list_id: UUID, body: schemas.SlotPatchIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionStateOut:
    with get_conn() as conn:
        return schemas.ConditionStateOut(**session_service.patch_slot(conn, list_id, body.field, body.value, principal))


@router.post("/{list_id}/message", response_model=schemas.ConditionStateOut)
def message(list_id: UUID, body: schemas.MessageIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionStateOut:
    raise NotImplementedError("message slot extraction is not implemented")

@router.post("/{list_id}/answer", response_model=schemas.ConditionStateOut)
def answer(list_id: UUID, body: schemas.AnswerIn, principal: Principal = Depends(optional_principal)) -> schemas.ConditionStateOut:
    raise NotImplementedError("answer mapping is not implemented")

@router.post("/{list_id}/recommend", response_model=schemas.RecommendResultOut)
def recommend(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    raise NotImplementedError("DB candidate selection is not implemented")

@router.get("/{list_id}/result", response_model=schemas.RecommendResultOut)
def result(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.RecommendResultOut:
    raise NotImplementedError("stored recommendation result mapping is not implemented")
