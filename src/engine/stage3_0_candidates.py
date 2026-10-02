"""[3-0] 후보 수집.

[2]와 [3-A] 사이의 별도 스텝. 실시간 커머스 데이터 API 호출·캐시·재시도를
필터 로직에서 격리한다. 재탐색 시에는 스킵(이미 수집된 후보 재사용).
데모: 로컬 합성 카탈로그만 읽음 (제휴 커머스 API는 최종에서).

"""
from __future__ import annotations

import os

from src.dto import Candidate, RequirementSpec
from src.engine import LogFn
from src.repo.catalog_repo import load_candidates_by_slot, load_candidates_by_slot_from_db


def load_pc_catalog(log: LogFn, *, catalog_source: str | None = None) -> dict[str, list[Candidate]]:
    """PC 카탈로그 로드 — [3-0]과 견적 점검의 매칭 미리보기(owned_parts.preview_current_specs)가
    함께 쓴다. 같은 카탈로그를 봐야 화면에 보이는 매칭과 실제 추천 계산의 매칭이 어긋나지 않는다.

    CATALOG_SOURCE=mock일 때만 합성 카탈로그를 선택한다. DB 경로의 연결 오류나 빈 결과는
    mock 카탈로그로 숨기지 않고 호출자에게 전파한다."""
    source = catalog_source if catalog_source is not None else os.environ.get("CATALOG_SOURCE", "db")
    if source == "mock":
        by_slot = load_candidates_by_slot()
    elif source == "db":
        from src.db import get_conn

        with get_conn() as conn:
            by_slot = load_candidates_by_slot_from_db(conn)
        if not any(by_slot.values()):
            raise RuntimeError("DB PC catalog is empty")
        summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
        log(f"      [DB] 실제 수집 카탈로그 로드 → 슬롯별 후보: {summary}")
        return by_slot
    else:
        raise ValueError(f"unsupported CATALOG_SOURCE: {source}")
    summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
    log(f"      [MOCK] 합성 카탈로그 로드 → 슬롯별 후보: {summary}")
    return by_slot


def run(spec: RequirementSpec, log: LogFn, *, catalog_source: str | None = None) -> dict[str, list[Candidate]]:
    log("[3-0] 후보 수집 ...")
    if spec.category == "computer":
        return load_pc_catalog(log, catalog_source=catalog_source)
    raise NotImplementedError(f"stage3_0: 지원하지 않는 카테고리입니다: {spec.category}")

