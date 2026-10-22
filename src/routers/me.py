"""/me/* — 내 현재 PC(C-1)와 사용자별 JSON 문서(C-2). 모두 로그인 필요(비로그인 401)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from src.auth import ratelimit
from src.auth.deps import Principal, optional_principal
from src.config import ME_WRITE_LIMIT_PER_MIN
from src.db import get_conn
from src.errors import RateLimited
from src.services import me_service as svc

router = APIRouter(prefix="/me", tags=["me"])


class PcIn(BaseModel):
    parts: dict[str, str] = Field(default_factory=dict, description="칸 이름(cpu·gpu·ram·storage·board·psu·cooler·case) → 사용자가 쓴 부품 이름")
    source: str = Field(default="", description="어디서 가져왔는지 안내 문구(직접 입력·견적서 불러오기 등)")
    title: str = ""


class DocumentIn(BaseModel):
    value: Any = Field(description="저장할 JSON 값(객체·배열·문자열·숫자 모두 가능)")


def _write_limit(principal: Principal) -> None:
    if principal.user_id is not None and not ratelimit.allow(f"me-write:{principal.user_id}", limit=ME_WRITE_LIMIT_PER_MIN, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")


@router.get("/pc")
def get_pc(principal: Principal = Depends(optional_principal)) -> dict | None:
    """저장한 내 PC. 없으면 null."""
    with get_conn() as conn:
        return svc.get_pc(conn, principal)


@router.put("/pc")
def put_pc(body: PcIn, principal: Principal = Depends(optional_principal)) -> dict:
    """전체 교체. 칸마다 최대 120자, 한 칸 이상 필요."""
    _write_limit(principal)
    with get_conn() as conn:
        return svc.put_pc(conn, principal, parts=body.parts, source=body.source, title=body.title)


@router.delete("/pc", status_code=status.HTTP_204_NO_CONTENT)
def delete_pc(principal: Principal = Depends(optional_principal)) -> Response:
    _write_limit(principal)
    with get_conn() as conn:
        svc.delete_pc(conn, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/data")
def list_data(principal: Principal = Depends(optional_principal)) -> dict:
    """내 문서 목록(키·크기·수정 시각)과 한도."""
    with get_conn() as conn:
        return svc.list_data(conn, principal)


@router.get("/data/{key}")
def get_data(key: str, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.get_data(conn, principal, key)


@router.put("/data/{key}")
def put_data(key: str, body: DocumentIn, principal: Principal = Depends(optional_principal)) -> dict:
    """문서 하나를 통째로 교체한다. 키는 영문 소문자·숫자·`.` `_` `:` `-`(64자), 문서 256KB·깊이 32, 사용자당 50개."""
    _write_limit(principal)
    with get_conn() as conn:
        return svc.put_data(conn, principal, key, body.value)


@router.delete("/data/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data(key: str, principal: Principal = Depends(optional_principal)) -> Response:
    _write_limit(principal)
    with get_conn() as conn:
        svc.delete_data(conn, principal, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
