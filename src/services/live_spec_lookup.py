"""DB 미보유 부품·주변기기 실시간 스펙 검색 — docs/미보유부품_실시간스펙검색_설계.md.

2단계(이 파일의 현재 범위): 검증(critique) 구조화 출력 스키마만 정의한다. 검색 호출·캐시
읽기/쓰기·pc_check 연동은 3~4단계에서 이 파일에 이어서 추가한다(아직 없음).

`SupportedFields`의 필드명은 src/engine/owned_parts.py가 이미 쓰는 specs 키(`_SPEC_LABEL`)와
한 글자도 다르면 안 된다 — 다르면 호환성 검사 로직이 이 결과를 못 읽는다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SupportedFields(BaseModel):
    """스니펫에 실제로 적힌 값만 채운다(비어 있으면 null) — 지어낸 값 금지(프롬프트 규칙 2·3).

    extra="forbid" — 모델이 스키마 밖 필드(owned_parts.py가 모르는 키)를 지어내면 조용히
    버리지 않고 검증에서 걸린다."""

    model_config = ConfigDict(extra="forbid")

    socket: str | None = None
    mem_type: str | None = None
    wattage_w: int | None = None
    speed_mts: int | None = None
    capacity_gb: int | None = None
    module_config: str | None = None
    form_factor: str | None = None
    supports_form_factors: str | None = None
    cooling_type: str | None = None
    radiator_mm: int | None = None
    height_mm: int | None = None
    interface: str | None = None


class LiveSpecLookupResult(BaseModel):
    """live_spec_lookup_system()의 구조화 출력 계약.

    relevant=False 이거나 supported_fields가 전부 비어 있으면 호출자는 기존처럼
    "모름"으로 폴백한다(설계 문서 §3) — 이 모델 자체는 그 폴백 판단을 하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    supported_fields: SupportedFields = Field(default_factory=SupportedFields)
    source_url: str | None = None

    def has_any_field(self) -> bool:
        return any(v is not None for v in self.supported_fields.model_dump().values())
